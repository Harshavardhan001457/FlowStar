/*
 * Components 1-2: FlowStar-inspired dumbbell topology with TCP traffic.
 *
 * BulkSendApplication is used because it continuously offers TCP data as
 * quickly as the protocol and network allow, unlike a constant-bit-rate UDP
 * source. PacketSinkApplication records bytes received at each destination.
 */

#include "ns3/core-module.h"
#include "ns3/applications-module.h"
#include "ns3/flow-monitor-module.h"
#include "ns3/internet-module.h"
#include "ns3/network-module.h"
#include "ns3/point-to-point-module.h"
#include "ns3/rng-seed-manager.h"
#include "ns3/traffic-control-module.h"
#include "ns3/ipv4-queue-disc-item.h"
#include "ns3/tcp-header.h"
#include "ns3/udp-header.h"

#include <filesystem>
#include <fstream>
#include <algorithm>
#include <iomanip>
#include <limits>
#include <map>
#include <sstream>
#include <vector>

using namespace ns3;

namespace
{

constexpr uint32_t ROUTER_NODE_COUNT = 2;
constexpr uint32_t MAX_SUPPORTED_FLOWS = 10;
constexpr uint32_t LINK_COUNT = 2;
constexpr uint32_t QUEUE_LIMIT_PACKETS = 100;
constexpr double SIMULATION_DURATION_SECONDS = 20.0;
constexpr double DEFAULT_APPLICATION_START_SECONDS = 1.0;
constexpr double DEFAULT_APPLICATION_STOP_SECONDS = 19.0;
constexpr double DEFAULT_SINK_START_SECONDS = 0.5;
constexpr uint32_t DEFAULT_PACKET_SIZE_BYTES = 1000;
constexpr uint16_t FIRST_DESTINATION_PORT = 5001;
constexpr double DEFAULT_MEASUREMENT_INTERVAL_SECONDS = 0.1;
constexpr uint32_t DQA_QUEUE_CLASS_COUNT = 2;
constexpr uint32_t HYBRID_QUEUE_CLASS_COUNT = 4;
constexpr double DQA_CONTROL_INTERVAL_SECONDS = 0.2;
constexpr double DQA_SWITCH_THRESHOLD = 0.2;
constexpr double DQA_SWITCH_COOLDOWN_SECONDS = 1.0;

struct QueueDropRecord
{
    std::string direction;
    std::string queueLayer;
    uint32_t packetSize;
    double timeSeconds;
};

class DynamicQueueAssignmentDisc : public QueueDisc
{
  public:
    static TypeId GetTypeId()
    {
        static TypeId tid =
            TypeId("ns3::DynamicQueueAssignmentDisc")
                .SetParent<QueueDisc>()
                .SetGroupName("TrafficControl")
                .AddConstructor<DynamicQueueAssignmentDisc>()
                .AddAttribute("MaxSize",
                              "Maximum total packets held by the DQA queue disc.",
                              QueueSizeValue(QueueSize("100p")),
                              MakeQueueSizeAccessor(&QueueDisc::SetMaxSize,
                                                    &QueueDisc::GetMaxSize),
                              MakeQueueSizeChecker())
                .AddAttribute("QueueClassCount",
                              "Number of internal logical queue classes.",
                              UintegerValue(DQA_QUEUE_CLASS_COUNT),
                              MakeUintegerAccessor(&DynamicQueueAssignmentDisc::m_queueClassCount),
                              MakeUintegerChecker<uint32_t>(DQA_QUEUE_CLASS_COUNT,
                                                            MAX_SUPPORTED_FLOWS + 1));
        return tid;
    }

    DynamicQueueAssignmentDisc()
        : QueueDisc(QueueDiscSizePolicy::MULTIPLE_QUEUES, QueueSizeUnit::PACKETS)
    {
    }

    void SetFlowQueue(uint16_t destinationPort, uint32_t queueIndex)
    {
        NS_ABORT_MSG_UNLESS(queueIndex < m_queueClassCount,
                            "Invalid DQA queue class");
        m_flowQueues[destinationPort] = queueIndex;
    }

    uint32_t GetFlowQueue(uint16_t destinationPort) const
    {
        auto it = m_flowQueues.find(destinationPort);
        return it == m_flowQueues.end() ? 0 : it->second;
    }

    uint32_t GetQueuePackets(uint32_t queueIndex) const
    {
        NS_ABORT_MSG_UNLESS(queueIndex < m_queueClassCount &&
                                queueIndex < GetNInternalQueues(),
                            "Invalid DQA queue class");
        return GetInternalQueue(queueIndex)->GetNPackets();
    }

    uint32_t GetQueueBytes(uint32_t queueIndex) const
    {
        NS_ABORT_MSG_UNLESS(queueIndex < m_queueClassCount &&
                                queueIndex < GetNInternalQueues(),
                            "Invalid DQA queue class");
        return GetInternalQueue(queueIndex)->GetNBytes();
    }

    uint32_t GetRecentEnqueues(uint16_t destinationPort) const
    {
        auto it = m_recentEnqueues.find(destinationPort);
        return it == m_recentEnqueues.end() ? 0 : it->second;
    }

    void ResetRecentEnqueues()
    {
        m_recentEnqueues.clear();
    }

  private:
    bool DoEnqueue(Ptr<QueueDiscItem> item) override
    {
        if (GetCurrentSize() >= GetMaxSize())
        {
            DropBeforeEnqueue(item, "DQA queue disc limit exceeded");
            return false;
        }
        const uint16_t destinationPort = GetDestinationPort(item);
        const uint32_t queueIndex = GetFlowQueue(destinationPort);
        const bool accepted = GetInternalQueue(queueIndex)->Enqueue(item);
        if (accepted)
        {
            ++m_recentEnqueues[destinationPort];
        }
        return accepted;
    }

    Ptr<QueueDiscItem> DoDequeue() override
    {
        uint32_t selectedQueue = 0;
        for (uint32_t index = 1; index < m_queueClassCount; ++index)
        {
            if (GetInternalQueue(index)->GetNPackets() >
                GetInternalQueue(selectedQueue)->GetNPackets())
            {
                selectedQueue = index;
            }
        }
        return GetInternalQueue(selectedQueue)->Dequeue();
    }

    Ptr<const QueueDiscItem> DoPeek() override
    {
        uint32_t selectedQueue = 0;
        for (uint32_t index = 1; index < m_queueClassCount; ++index)
        {
            if (GetInternalQueue(index)->GetNPackets() >
                GetInternalQueue(selectedQueue)->GetNPackets())
            {
                selectedQueue = index;
            }
        }
        return GetInternalQueue(selectedQueue)->Peek();
    }

    bool CheckConfig() override
    {
        if (GetNQueueDiscClasses() != 0 || GetNPacketFilters() != 0)
        {
            return false;
        }
        if (GetNInternalQueues() == 0)
        {
            ObjectFactory factory;
            factory.SetTypeId("ns3::DropTailQueue<QueueDiscItem>");
            factory.Set("MaxSize", QueueSizeValue(GetMaxSize()));
            for (uint32_t index = 0; index < m_queueClassCount; ++index)
            {
                AddInternalQueue(factory.Create<InternalQueue>());
            }
        }
        return GetNInternalQueues() == m_queueClassCount;
    }

    void InitializeParams() override
    {
    }

    static uint16_t GetDestinationPort(Ptr<QueueDiscItem> item)
    {
        Ptr<Ipv4QueueDiscItem> ipv4Item = DynamicCast<Ipv4QueueDiscItem>(item);
        if (!ipv4Item ||
        (ipv4Item->GetHeader().GetProtocol() != 6 &&
         ipv4Item->GetHeader().GetProtocol() != 17))
        {
        return 0;
        }
        if (ipv4Item->GetHeader().GetProtocol() == 6)
        {
        TcpHeader header;
        if (ipv4Item->GetPacket()->PeekHeader(header) == 0)
        {
            return 0;
        }
        return header.GetDestinationPort();
        }
        UdpHeader header;
        if (ipv4Item->GetPacket()->PeekHeader(header) == 0)
        {
        return 0;
        }
        return header.GetDestinationPort();
    }

    std::map<uint16_t, uint32_t> m_flowQueues;
    std::map<uint16_t, uint32_t> m_recentEnqueues;
    uint32_t m_queueClassCount = DQA_QUEUE_CLASS_COUNT;
};

NS_OBJECT_ENSURE_REGISTERED(DynamicQueueAssignmentDisc);

class DqaController
{
  public:
    DqaController(const std::string& outputDirectory,
                  const std::vector<Ptr<DynamicQueueAssignmentDisc>>& queueDiscs,
                  const std::vector<uint16_t>& destinationPorts,
                  uint32_t queueLimitPackets,
                  double simulationDurationSeconds)
        : m_queueDiscs(queueDiscs),
          m_destinationPorts(destinationPorts),
          m_queueLimitPackets(queueLimitPackets),
          m_simulationDurationSeconds(simulationDurationSeconds)
    {
        std::filesystem::create_directories(outputDirectory);
        m_queueFile.open(outputDirectory + "/dqa_queue_timeseries.csv");
        m_assignmentFile.open(outputDirectory + "/dqa_assignments.csv");
        NS_ABORT_MSG_UNLESS(m_queueFile && m_assignmentFile,
                            "Unable to open DQA measurement files");
        m_queueFile << "time_s,direction,queue_class,occupancy_packets,occupancy_bytes,"
                       "configured_limit_packets\n";
        m_assignmentFile
            << "time_s,direction,destination_port,old_queue_class,new_queue_class,"
               "busy_occupancy_packets,quiet_occupancy_packets,threshold_packets,reason\n";
        m_lastSwitchSeconds.assign(queueDiscs.size(),
                                   std::numeric_limits<double>::lowest());
        for (auto& queueDisc : m_queueDiscs)
        {
            for (uint32_t index = 0; index < destinationPorts.size(); ++index)
            {
                queueDisc->SetFlowQueue(destinationPorts[index],
                                         index % DQA_QUEUE_CLASS_COUNT);
            }
        }
    }

    void Start()
    {
        for (uint32_t direction = 0; direction < m_queueDiscs.size(); ++direction)
        {
            WriteAssignments(direction, "initial");
        }
        Simulator::ScheduleNow(&DqaController::Control, this);
    }

  private:
    void Control()
    {
        const double now = Simulator::Now().GetSeconds();
        for (uint32_t direction = 0; direction < m_queueDiscs.size(); ++direction)
        {
            const auto& queueDisc = m_queueDiscs[direction];
            for (uint32_t queueIndex = 0; queueIndex < DQA_QUEUE_CLASS_COUNT; ++queueIndex)
            {
                m_queueFile << now << ',' << (direction == 0 ? "left_to_right" : "right_to_left")
                            << ',' << queueIndex << ',' << queueDisc->GetQueuePackets(queueIndex)
                            << ',' << queueDisc->GetQueueBytes(queueIndex) << ','
                            << m_queueLimitPackets << '\n';
            }

            const uint32_t busyQueue =
                queueDisc->GetQueuePackets(0) >= queueDisc->GetQueuePackets(1) ? 0 : 1;
            const uint32_t quietQueue = 1 - busyQueue;
            const uint32_t busyPackets = queueDisc->GetQueuePackets(busyQueue);
            const uint32_t quietPackets = queueDisc->GetQueuePackets(quietQueue);
            const bool enoughDifference =
                busyPackets > quietPackets &&
                (busyPackets - quietPackets) >=
                    static_cast<uint32_t>(m_queueLimitPackets * DQA_SWITCH_THRESHOLD);
            const bool cooldownElapsed =
                now - m_lastSwitchSeconds[direction] >= DQA_SWITCH_COOLDOWN_SECONDS;

            if (enoughDifference && cooldownElapsed)
            {
                uint16_t candidatePort = 0;
                uint32_t candidateCount = 0;
                uint32_t assignedCount = 0;
                for (const auto port : m_destinationPorts)
                {
                    if (queueDisc->GetFlowQueue(port) == busyQueue)
                    {
                        ++assignedCount;
                        if (queueDisc->GetRecentEnqueues(port) >= candidateCount)
                        {
                            candidatePort = port;
                            candidateCount = queueDisc->GetRecentEnqueues(port);
                        }
                    }
                }
                if (assignedCount >= 2 && candidatePort != 0)
                {
                    queueDisc->SetFlowQueue(candidatePort, quietQueue);
                    m_lastSwitchSeconds[direction] = now;
                    m_assignmentFile << now << ','
                                     << (direction == 0 ? "left_to_right" : "right_to_left")
                                     << ',' << candidatePort << ',' << busyQueue << ','
                                     << quietQueue << ',' << busyPackets << ',' << quietPackets
                                     << ',' << (m_queueLimitPackets * DQA_SWITCH_THRESHOLD)
                                     << ",occupancy_difference\n";
                }
            }
            queueDisc->ResetRecentEnqueues();
        }

        if (now + DQA_CONTROL_INTERVAL_SECONDS <= m_simulationDurationSeconds)
        {
            Simulator::Schedule(Seconds(DQA_CONTROL_INTERVAL_SECONDS),
                                &DqaController::Control,
                                this);
        }
    }

    void WriteAssignments(uint32_t direction, const std::string& event)
    {
        const double now = Simulator::Now().GetSeconds();
        for (const auto port : m_destinationPorts)
        {
            m_assignmentFile << now << ','
                             << (direction == 0 ? "left_to_right" : "right_to_left") << ','
                             << port << ",,"
                             << m_queueDiscs[direction]->GetFlowQueue(port)
                             << ",,,," << event << '\n';
        }
    }

    std::vector<Ptr<DynamicQueueAssignmentDisc>> m_queueDiscs;
    std::vector<uint16_t> m_destinationPorts;
    uint32_t m_queueLimitPackets;
    double m_simulationDurationSeconds;
    std::vector<double> m_lastSwitchSeconds;
    std::ofstream m_queueFile;
    std::ofstream m_assignmentFile;
};

class HybridStateManager
{
  public:
    HybridStateManager(const std::string& outputDirectory,
                       const std::vector<Ptr<DynamicQueueAssignmentDisc>>& queueDiscs,
                       const std::vector<uint16_t>& destinationPorts,
                       const std::vector<double>& flowStartTimes,
                       const std::vector<double>& flowStopTimes,
                       uint32_t dedicatedResourceLimit,
                       uint32_t fallbackQueueClass,
                       double simulationDurationSeconds)
        : m_queueDiscs(queueDiscs),
          m_destinationPorts(destinationPorts),
        m_flowStartTimes(flowStartTimes),
          m_flowStopTimes(flowStopTimes),
          m_dedicatedResourceLimit(dedicatedResourceLimit),
          m_fallbackQueueClass(fallbackQueueClass),
          m_simulationDurationSeconds(simulationDurationSeconds)
    {
        std::filesystem::create_directories(outputDirectory);
        m_stateFile.open(outputDirectory + "/hybrid_state.csv");
        NS_ABORT_MSG_UNLESS(m_stateFile, "Unable to open hybrid state CSV");
        m_stateFile
            << "time_s,direction,destination_port,assignment,state_event,dedicated_resource,"
               "active_state_entries,dedicated_flow_count,shared_flow_count\n";
        for (uint32_t index = 0; index < m_destinationPorts.size(); ++index)
        {
            FlowState state;
            state.assignment = m_fallbackQueueClass;
            state.active = false;
            m_states[m_destinationPorts[index]] = state;
            for (const auto& queueDisc : m_queueDiscs)
            {
                queueDisc->SetFlowQueue(m_destinationPorts[index], m_fallbackQueueClass);
            }
        }
    }

    void Start()
    {
        for (uint32_t index = 0; index < m_destinationPorts.size(); ++index)
        {
            Simulator::Schedule(Seconds(m_flowStartTimes[index]),
                                &HybridStateManager::ActivateFlow,
                                this,
                                m_destinationPorts[index]);
            if (m_flowStopTimes[index] < m_simulationDurationSeconds)
            {
                Simulator::Schedule(Seconds(m_flowStopTimes[index] + 0.001),
                                    &HybridStateManager::ReleaseFlow,
                                    this,
                                    m_destinationPorts[index]);
            }
        }
    }

  private:
    struct FlowState
    {
        uint32_t assignment = 0;
        bool dedicated = false;
        bool active = false;
    };

    void ActivateFlow(uint16_t destinationPort)
    {
        auto it = m_states.find(destinationPort);
        NS_ABORT_MSG_UNLESS(it != m_states.end() && !it->second.active,
                            "Invalid or duplicate hybrid flow activation");
        uint32_t dedicatedResource = m_dedicatedResourceLimit;
        for (uint32_t resource = 0; resource < m_dedicatedResourceLimit; ++resource)
        {
            bool occupied = false;
            for (const auto& entry : m_states)
            {
                if (entry.second.active && entry.second.dedicated &&
                    entry.second.assignment == resource)
                {
                    occupied = true;
                    break;
                }
            }
            if (!occupied)
            {
                dedicatedResource = resource;
                break;
            }
        }
        it->second.active = true;
        it->second.dedicated = dedicatedResource < m_dedicatedResourceLimit;
        it->second.assignment = it->second.dedicated ? dedicatedResource : m_fallbackQueueClass;
        for (uint32_t direction = 0; direction < m_queueDiscs.size(); ++direction)
        {
            m_queueDiscs[direction]->SetFlowQueue(destinationPort, it->second.assignment);
            Write(direction, destinationPort, "created");
            Write(direction, destinationPort, "initial_assignment");
        }
    }

    void ReleaseFlow(uint16_t destinationPort)
    {
        auto it = m_states.find(destinationPort);
        if (it == m_states.end() || !it->second.active)
        {
            return;
        }
        it->second.active = false;
        const uint32_t releasedResource = it->second.assignment;
        it->second.dedicated = false;
        for (uint32_t direction = 0; direction < m_queueDiscs.size(); ++direction)
        {
            Write(direction, destinationPort, "released");
        }

        for (const auto candidatePort : m_destinationPorts)
        {
            auto candidate = m_states.find(candidatePort);
            if (candidate == m_states.end() || !candidate->second.active ||
                candidate->second.dedicated)
            {
                continue;
            }
            candidate->second.assignment = releasedResource;
            candidate->second.dedicated = true;
            for (uint32_t direction = 0; direction < m_queueDiscs.size(); ++direction)
            {
                m_queueDiscs[direction]->SetFlowQueue(candidatePort, releasedResource);
                Write(direction, candidatePort, "promoted_to_dedicated");
            }
            break;
        }
        CleanupInactive();
    }

    void CleanupInactive()
    {
        for (auto it = m_states.begin(); it != m_states.end();)
        {
            if (!it->second.active)
            {
                it = m_states.erase(it);
            }
            else
            {
                ++it;
            }
        }
    }

    void Write(uint32_t direction, uint16_t port, const std::string& event)
    {
        uint32_t dedicatedCount = 0;
        uint32_t sharedCount = 0;
        for (const auto& entry : m_states)
        {
            if (entry.second.active && entry.second.dedicated)
            {
                ++dedicatedCount;
            }
            else if (entry.second.active)
            {
                ++sharedCount;
            }
        }
        const auto it = m_states.find(port);
        const uint32_t assignment = it == m_states.end() ? m_fallbackQueueClass
                                                          : it->second.assignment;
        m_stateFile << Simulator::Now().GetSeconds() << ','
                    << (direction == 0 ? "left_to_right" : "right_to_left") << ',' << port << ','
                    << assignment << ',' << event << ','
                    << (it != m_states.end() && it->second.dedicated
                            ? std::to_string(it->second.assignment)
                            : "shared")
                    << ',' << m_states.size() << ',' << dedicatedCount << ',' << sharedCount
                    << '\n';
    }

    std::vector<Ptr<DynamicQueueAssignmentDisc>> m_queueDiscs;
    std::vector<uint16_t> m_destinationPorts;
    std::vector<double> m_flowStartTimes;
    std::vector<double> m_flowStopTimes;
    uint32_t m_dedicatedResourceLimit;
    uint32_t m_fallbackQueueClass;
    double m_simulationDurationSeconds;
    std::map<uint16_t, FlowState> m_states;
    std::ofstream m_stateFile;
};

class MeasurementCollector
{
  public:
    MeasurementCollector(const std::string& outputDirectory,
                         const std::vector<Ptr<PacketSink>>& packetSinks,
                         const std::vector<std::string>& flowIds,
                         const std::vector<Ptr<Queue<Packet>>>& bottleneckQueues,
                         const std::vector<Ptr<DynamicQueueAssignmentDisc>>& dqaQueueDiscs,
                         uint32_t queueClassCount,
                         double simulationDurationSeconds,
                         double samplingIntervalSeconds,
                         uint32_t queueLimitPackets)
        : m_outputDirectory(outputDirectory),
          m_packetSinks(packetSinks),
          m_flowIds(flowIds),
          m_bottleneckQueues(bottleneckQueues),
          m_dqaQueueDiscs(dqaQueueDiscs),
          m_queueClassCount(queueClassCount),
          m_simulationDurationSeconds(simulationDurationSeconds),
          m_samplingIntervalSeconds(samplingIntervalSeconds),
          m_queueLimitPackets(queueLimitPackets),
          m_previousBytes(flowIds.size(), 0)
    {
        std::filesystem::create_directories(m_outputDirectory);
        m_throughputFile.open(m_outputDirectory + "/throughput_timeseries.csv");
        m_queueFile.open(m_outputDirectory + "/queue_timeseries.csv");
        m_physicalQueueFile.open(m_outputDirectory + "/physical_queue_timeseries.csv");
        m_queueDiscFile.open(m_outputDirectory + "/queuedisc_timeseries.csv");
        m_logicalQueueFile.open(m_outputDirectory + "/logical_queue_timeseries.csv");
        m_dropFile.open(m_outputDirectory + "/packet_drops.csv");
        m_physicalDropFile.open(m_outputDirectory + "/physical_queue_drops.csv");
        m_queueDiscDropFile.open(m_outputDirectory + "/queuedisc_root_drops.csv");
        m_internalDropFile.open(m_outputDirectory + "/internal_queuedisc_drops.csv");
        NS_ABORT_MSG_UNLESS(m_throughputFile && m_queueFile && m_physicalQueueFile &&
                                m_queueDiscFile && m_logicalQueueFile && m_dropFile &&
                                m_physicalDropFile && m_queueDiscDropFile &&
                                m_internalDropFile,
                            "Unable to open measurement CSV files");

        m_throughputFile << "time_s,flow_id,cumulative_rx_bytes,interval_rx_bytes,"
                            "interval_throughput_bps\n";
        m_queueFile << "time_s,queue_id,occupancy_packets,occupancy_bytes,"
                       "configured_limit_packets\n";
        m_physicalQueueFile << "time_s,direction,occupancy_packets,occupancy_bytes,"
                               "configured_limit_packets,queue_object\n";
        m_queueDiscFile << "time_s,direction,occupancy_packets,occupancy_bytes,"
                           "configured_limit_packets,queue_object\n";
        m_logicalQueueFile << "time_s,direction,queue_class,occupancy_packets,"
                              "occupancy_bytes,configured_limit_packets,queue_object\n";
        m_dropFile << "time_s,queue_id,trace_source,packet_size_bytes\n";
        m_physicalDropFile << "time_s,direction,trace_source,packet_size_bytes,queue_object\n";
        m_queueDiscDropFile << "time_s,direction,trace_source,packet_size_bytes,queue_object\n";
        m_internalDropFile << "time_s,direction,trace_source,packet_size_bytes,queue_object\n";
    }

    void Start()
    {
        Simulator::ScheduleNow(&MeasurementCollector::Sample, this, Seconds(0));
        Simulator::Schedule(Seconds(m_simulationDurationSeconds),
                            &MeasurementCollector::Sample,
                            this,
                            Seconds(m_simulationDurationSeconds));
    }

    void RecordDrop(const std::string& queueId, const std::string& queueLayer,
                    const std::string& traceSource,
                    Ptr<const Packet> packet)
    {
        m_dropRecords.push_back(
            {queueId, queueLayer, packet ? packet->GetSize() : 0, Simulator::Now().GetSeconds()});
    }

    void RecordLeftToRightDrop(Ptr<const Packet> packet)
    {
        RecordDrop("left_to_right", "physical_netdevice", "Drop", packet);
    }

    void RecordRightToLeftDrop(Ptr<const Packet> packet)
    {
        RecordDrop("right_to_left", "physical_netdevice", "Drop", packet);
    }

    void RecordDqaLeftToRightDrop(Ptr<const QueueDiscItem> item)
    {
        RecordDrop("left_to_right",
                   "internal_queuedisc",
                   "DQAInternalQueueDrop",
                   item ? item->GetPacket() : nullptr);
    }

    void RecordDqaRightToLeftDrop(Ptr<const QueueDiscItem> item)
    {
        RecordDrop("right_to_left",
                   "internal_queuedisc",
                   "DQAInternalQueueDrop",
                   item ? item->GetPacket() : nullptr);
    }

    void RecordQueueDiscLeftToRightDrop(Ptr<const QueueDiscItem> item)
    {
        RecordDrop("left_to_right",
                   "root_queuedisc",
                   "QueueDiscDrop",
                   item ? item->GetPacket() : nullptr);
    }

    void RecordQueueDiscRightToLeftDrop(Ptr<const QueueDiscItem> item)
    {
        RecordDrop("right_to_left",
                   "root_queuedisc",
                   "QueueDiscDrop",
                   item ? item->GetPacket() : nullptr);
    }

    void WriteFlowStatistics(FlowMonitorHelper& flowMonitorHelper,
                             Ptr<FlowMonitor> monitor,
                             const std::vector<uint16_t>& destinationPorts,
                             uint8_t protocol)
    {
        std::ofstream output(m_outputDirectory + "/flow_statistics.csv");
        NS_ABORT_MSG_UNLESS(output, "Unable to open flow statistics CSV");
        output << "flow_id,source_ip,destination_ip,source_port,destination_port,protocol,"
                  "tx_packets,rx_packets,tx_bytes,rx_bytes,average_delay_s,"
                  "packet_delivery_ratio,lost_packets,first_tx_time_s,last_rx_time_s,"
                  "average_throughput_bps,application_rx_bytes\n";

        Ptr<Ipv4FlowClassifier> classifier =
            DynamicCast<Ipv4FlowClassifier>(flowMonitorHelper.GetClassifier());
        NS_ABORT_MSG_UNLESS(classifier, "IPv4 FlowMonitor classifier is unavailable");

        monitor->CheckForLostPackets();
        const auto& flowStats = monitor->GetFlowStats();
        for (uint32_t flowIndex = 0; flowIndex < destinationPorts.size(); ++flowIndex)
        {
            bool found = false;
            for (const auto& entry : flowStats)
            {
                const Ipv4FlowClassifier::FiveTuple tuple =
                    classifier->FindFlow(entry.first);
                if (tuple.destinationPort != destinationPorts[flowIndex] ||
                    tuple.protocol != protocol)
                {
                    continue;
                }

                const FlowMonitor::FlowStats& stats = entry.second;
                const double receivedPackets = stats.rxPackets;
                const std::string deliveryRatio =
                    stats.txPackets > 0 ? std::to_string(receivedPackets / stats.txPackets)
                                        : "undefined";
                const std::string averageThroughput =
                    stats.timeLastRxPacket > stats.timeFirstTxPacket
                        ? std::to_string((stats.rxBytes * 8.0) /
                                         (stats.timeLastRxPacket -
                                          stats.timeFirstTxPacket)
                                             .GetSeconds())
                        : "undefined";
                const std::string averageDelay =
                    receivedPackets > 0
                        ? std::to_string(stats.delaySum.GetSeconds() / receivedPackets)
                        : "undefined";
                const std::string firstTxTime =
                    stats.txPackets > 0 ? std::to_string(stats.timeFirstTxPacket.GetSeconds())
                                        : "undefined";
                const std::string lastRxTime =
                    stats.rxPackets > 0 ? std::to_string(stats.timeLastRxPacket.GetSeconds())
                                        : "undefined";
                output << m_flowIds[flowIndex] << ',' << tuple.sourceAddress << ','
                       << tuple.destinationAddress << ',' << tuple.sourcePort << ','
                       << tuple.destinationPort << ',' << static_cast<uint32_t>(tuple.protocol)
                       << ',' << stats.txPackets << ',' << stats.rxPackets << ','
                       << stats.txBytes << ',' << stats.rxBytes << ',' << averageDelay << ','
                       << deliveryRatio << ',' << stats.lostPackets << ','
                       << firstTxTime << ',' << lastRxTime << ',' << averageThroughput << ','
                       << m_packetSinks[flowIndex]->GetTotalRx() << '\n';
                found = true;
                break;
            }
            NS_ABORT_MSG_UNLESS(found, "FlowMonitor did not find an expected TCP flow");
        }
    }

    void WriteDropRecords()
    {
        for (uint32_t index = 0; index < m_dropRecords.size(); ++index)
        {
            const QueueDropRecord& record = m_dropRecords[index];
            m_dropFile << record.timeSeconds << ',' << record.direction << ','
                       << (record.queueLayer == "physical_netdevice"
                               ? "Drop"
                               : record.queueLayer == "root_queuedisc" ? "QueueDiscDrop"
                                                                        : "DQAInternalQueueDrop")
                       << ',' << record.packetSize << '\n';
            auto& output = record.queueLayer == "physical_netdevice"
                               ? m_physicalDropFile
                               : record.queueLayer == "root_queuedisc"
                                     ? m_queueDiscDropFile
                                     : m_internalDropFile;
            output << record.timeSeconds << ',' << record.direction << ','
                   << (record.queueLayer == "physical_netdevice"
                           ? "Drop"
                           : record.queueLayer == "root_queuedisc" ? "QueueDiscDrop"
                                                                    : "DQAInternalQueueDrop")
                   << ',' << record.packetSize << ','
                   << (record.queueLayer == "physical_netdevice"
                           ? "PointToPointNetDevice::Queue"
                           : record.queueLayer == "root_queuedisc"
                                 ? "QueueDisc::Root"
                                 : "QueueDisc::InternalQueue")
                   << '\n';
        }
    }

    uint64_t GetTotalApplicationBytes() const
    {
        uint64_t total = 0;
        for (const auto& sink : m_packetSinks)
        {
            total += sink->GetTotalRx();
        }
        return total;
    }

  private:
    void Sample(Time sampleTime)
    {
        const double timeSeconds = sampleTime.GetSeconds();
        for (uint32_t index = 0; index < m_packetSinks.size(); ++index)
        {
            const uint64_t cumulativeBytes = m_packetSinks[index]->GetTotalRx();
            if (m_havePreviousSample)
            {
                const uint64_t intervalBytes = cumulativeBytes - m_previousBytes[index];
                const double intervalSeconds = timeSeconds - m_previousTimeSeconds;
                m_throughputFile << timeSeconds << ',' << m_flowIds[index] << ','
                                 << cumulativeBytes << ',' << intervalBytes << ','
                                 << (intervalBytes * 8.0) / intervalSeconds << '\n';
            }
            m_previousBytes[index] = cumulativeBytes;
        }
        m_previousTimeSeconds = timeSeconds;
        m_havePreviousSample = true;

        for (uint32_t index = 0; index < m_bottleneckQueues.size(); ++index)
        {
            const std::string direction = index == 0 ? "left_to_right" : "right_to_left";
            const uint32_t physicalPackets = m_bottleneckQueues[index]->GetNPackets();
            const uint32_t physicalBytes = m_bottleneckQueues[index]->GetNBytes();
            m_physicalQueueFile << timeSeconds << ',' << direction << ','
                                << physicalPackets << ',' << physicalBytes << ','
                                << m_queueLimitPackets << ",PointToPointNetDevice::Queue\n";
            m_queueFile << timeSeconds << ',' << direction << ',' << physicalPackets << ','
                        << physicalBytes << ',' << m_queueLimitPackets << '\n';
        }
        if (!m_dqaQueueDiscs.empty())
        {
            for (uint32_t directionIndex = 0; directionIndex < m_dqaQueueDiscs.size();
                 ++directionIndex)
            {
                uint32_t aggregatePackets = 0;
                uint32_t aggregateBytes = 0;
                for (uint32_t queue = 0; queue < m_queueClassCount; ++queue)
                {
                    const uint32_t packets =
                        m_dqaQueueDiscs[directionIndex]->GetQueuePackets(queue);
                    const uint32_t bytes = m_dqaQueueDiscs[directionIndex]->GetQueueBytes(queue);
                    aggregatePackets += packets;
                    aggregateBytes += bytes;
                    m_logicalQueueFile << timeSeconds << ','
                                       << (directionIndex == 0 ? "left_to_right"
                                                               : "right_to_left")
                                       << ',' << queue << ',' << packets << ',' << bytes << ','
                                       << m_queueLimitPackets << ",QueueDisc::InternalQueue\n";
                }
                m_queueDiscFile << timeSeconds << ','
                                << (directionIndex == 0 ? "left_to_right" : "right_to_left")
                                << ',' << aggregatePackets << ',' << aggregateBytes << ','
                                << m_queueLimitPackets << ",QueueDisc::RootAggregate\n";
            }
        }

        if (sampleTime < Seconds(m_simulationDurationSeconds))
        {
            Time nextSample = sampleTime + Seconds(m_samplingIntervalSeconds);
            if (nextSample > Seconds(m_simulationDurationSeconds))
            {
                nextSample = Seconds(m_simulationDurationSeconds);
            }
            Simulator::Schedule(nextSample - Simulator::Now(),
                                &MeasurementCollector::Sample,
                                this,
                                nextSample);
        }
    }

    std::string m_outputDirectory;
    std::vector<Ptr<PacketSink>> m_packetSinks;
    std::vector<std::string> m_flowIds;
    std::vector<Ptr<Queue<Packet>>> m_bottleneckQueues;
    std::vector<Ptr<DynamicQueueAssignmentDisc>> m_dqaQueueDiscs;
    uint32_t m_queueClassCount;
    double m_simulationDurationSeconds;
    double m_samplingIntervalSeconds;
    uint32_t m_queueLimitPackets;
    std::ofstream m_throughputFile;
    std::ofstream m_queueFile;
    std::ofstream m_physicalQueueFile;
    std::ofstream m_queueDiscFile;
    std::ofstream m_logicalQueueFile;
    std::ofstream m_dropFile;
    std::ofstream m_physicalDropFile;
    std::ofstream m_queueDiscDropFile;
    std::ofstream m_internalDropFile;
    std::vector<uint64_t> m_previousBytes;
    double m_previousTimeSeconds = 0;
    bool m_havePreviousSample = false;
    std::vector<QueueDropRecord> m_dropRecords;
};

} // namespace

int
main(int argc, char* argv[])
{
    std::string accessDataRate = "100Mbps";
    std::string accessDelay = "2ms";
    std::string bottleneckDataRate = "5Mbps";
    std::string bottleneckDelay = "10ms";
    double simulationDurationSeconds = SIMULATION_DURATION_SECONDS;
    std::string tcpVariant = "ns3::TcpNewReno";
    std::string trafficModel = "tcp";
    std::string offeredRate = "500Kbps";
    double applicationStartSeconds = DEFAULT_APPLICATION_START_SECONDS;
    double applicationStopSeconds = DEFAULT_APPLICATION_STOP_SECONDS;
    double sinkStartSeconds = DEFAULT_SINK_START_SECONDS;
    uint16_t destinationPort1 = FIRST_DESTINATION_PORT;
    uint16_t destinationPort2 = FIRST_DESTINATION_PORT + 1;
    uint16_t destinationPort3 = FIRST_DESTINATION_PORT + 2;
    uint64_t maximumBytes = 0;
    uint32_t packetSizeBytes = DEFAULT_PACKET_SIZE_BYTES;
    double measurementIntervalSeconds = DEFAULT_MEASUREMENT_INTERVAL_SECONDS;
    std::string outputDirectory = "results/baseline";
    uint32_t activeFlowCount = 3;
    uint32_t randomSeed = 1;
    uint64_t runNumber = 1;
    uint32_t queueLimitPackets = QUEUE_LIMIT_PACKETS;
    bool dynamicQueueAssignment = false;
    bool fixedQueueAssignment = false;
    bool hybridPerFlowState = false;
    uint32_t hybridDedicatedResources = DQA_QUEUE_CLASS_COUNT;
    bool temporaryCompetition = false;
    double competingFlowsStartSeconds = 6.0;
    double competingFlowsStopSeconds = 14.0;

    CommandLine commandLine(__FILE__);
    commandLine.AddValue("accessDataRate", "Data rate for source and destination access links",
                         accessDataRate);
    commandLine.AddValue("accessDelay", "Propagation delay for access links", accessDelay);
    commandLine.AddValue("bottleneckDataRate", "Data rate for the shared router link",
                         bottleneckDataRate);
    commandLine.AddValue("bottleneckDelay", "Propagation delay for the shared router link",
                         bottleneckDelay);
    commandLine.AddValue("simulationDuration", "Simulation duration in seconds",
                         simulationDurationSeconds);
    commandLine.AddValue("tcpVariant", "TCP congestion-control TypeId", tcpVariant);
    commandLine.AddValue("trafficModel", "Traffic workload: tcp or udp", trafficModel);
    commandLine.AddValue("offeredRate", "UDP offered rate per flow", offeredRate);
    commandLine.AddValue("applicationStart",
                         "Sender application start time in seconds",
                         applicationStartSeconds);
    commandLine.AddValue("applicationStop",
                         "Sender application stop time in seconds",
                         applicationStopSeconds);
    commandLine.AddValue("sinkStart", "Packet sink start time in seconds", sinkStartSeconds);
    commandLine.AddValue("destinationPort1", "Destination port for flow 1", destinationPort1);
    commandLine.AddValue("destinationPort2", "Destination port for flow 2", destinationPort2);
    commandLine.AddValue("destinationPort3", "Destination port for flow 3", destinationPort3);
    commandLine.AddValue("maximumBytes",
                         "Maximum bytes per BulkSendApplication (0 means unlimited)",
                         maximumBytes);
    commandLine.AddValue("packetSize", "BulkSend TCP payload size in bytes", packetSizeBytes);
    commandLine.AddValue("measurementInterval",
                         "Measurement sampling interval in seconds",
                         measurementIntervalSeconds);
    commandLine.AddValue("outputDirectory",
                         "Directory for measurement CSV and JSON output",
                         outputDirectory);
    commandLine.AddValue("activeFlows", "Number of active TCP flows (1 through 3)",
                         activeFlowCount);
    commandLine.AddValue("randomSeed", "NS-3 random seed", randomSeed);
    commandLine.AddValue("runNumber", "NS-3 random run number", runNumber);
    commandLine.AddValue("queueLimitPackets", "DropTail queue limit in packets",
                         queueLimitPackets);
    commandLine.AddValue("dynamicQueueAssignment",
                         "Enable congestion-aware software queue-class assignment",
                         dynamicQueueAssignment);
    commandLine.AddValue("fixedQueueAssignment",
                         "Install the QueueDisc with fixed initial assignments",
                         fixedQueueAssignment);
    commandLine.AddValue("hybridPerFlowState",
                         "Enable per-flow state and shared-resource fallback",
                         hybridPerFlowState);
    commandLine.AddValue("hybridDedicatedResources",
                         "Number of dedicated logical resources available to hybrid state",
                         hybridDedicatedResources);
    commandLine.AddValue("temporaryCompetition",
                         "Run flow 1 continuously while flows 2 and 3 compete temporarily",
                         temporaryCompetition);
    commandLine.AddValue("competingFlowsStart",
                         "Start time in seconds for temporary competing flows",
                         competingFlowsStartSeconds);
    commandLine.AddValue("competingFlowsStop",
                         "Stop time in seconds for temporary competing flows",
                         competingFlowsStopSeconds);
    commandLine.Parse(argc, argv);

    NS_ABORT_MSG_UNLESS(simulationDurationSeconds > 0,
                        "Simulation duration must be greater than zero");
    NS_ABORT_MSG_UNLESS(sinkStartSeconds >= 0 &&
                            sinkStartSeconds < applicationStartSeconds &&
                            applicationStartSeconds < applicationStopSeconds &&
                            applicationStopSeconds <= simulationDurationSeconds,
                        "Application and simulation times are invalid");
    NS_ABORT_MSG_UNLESS(packetSizeBytes > 0, "Packet size must be greater than zero");
    NS_ABORT_MSG_UNLESS(trafficModel == "tcp" || trafficModel == "udp",
                        "trafficModel must be tcp or udp");
    NS_ABORT_MSG_UNLESS(trafficModel != "udp" || !temporaryCompetition,
                        "UDP stress does not support temporary competition");
    NS_ABORT_MSG_UNLESS(measurementIntervalSeconds > 0,
                        "Measurement interval must be greater than zero");
    NS_ABORT_MSG_UNLESS(activeFlowCount >= 1 && activeFlowCount <= MAX_SUPPORTED_FLOWS,
                        "activeFlows must be between 1 and 10");
    NS_ABORT_MSG_UNLESS(queueLimitPackets > 0, "Queue limit must be greater than zero");
    NS_ABORT_MSG_UNLESS(!temporaryCompetition || activeFlowCount == 3,
                        "Temporary competition requires three active flows");
    NS_ABORT_MSG_UNLESS(!temporaryCompetition ||
                            (applicationStartSeconds <= competingFlowsStartSeconds &&
                             competingFlowsStartSeconds < competingFlowsStopSeconds &&
                             competingFlowsStopSeconds <= applicationStopSeconds),
                        "Temporary competition times must be within the sender interval");
    NS_ABORT_MSG_UNLESS(!hybridPerFlowState || dynamicQueueAssignment,
                        "Hybrid per-flow state requires dynamic queue assignment");
    NS_ABORT_MSG_UNLESS(!fixedQueueAssignment || !dynamicQueueAssignment,
                        "Fixed and dynamic queue assignment cannot both be enabled");
    NS_ABORT_MSG_UNLESS(!hybridPerFlowState || !temporaryCompetition,
                        "Hybrid per-flow state does not support temporary competition");
    NS_ABORT_MSG_UNLESS(!hybridPerFlowState ||
                            (hybridDedicatedResources >= 1 &&
                             hybridDedicatedResources <= activeFlowCount),
                        "Hybrid dedicated resources must be between 1 and activeFlows");
    NS_ABORT_MSG_UNLESS(destinationPort1 != destinationPort2 &&
                            destinationPort1 != destinationPort3 &&
                            destinationPort2 != destinationPort3,
                        "Destination ports must be distinct");

    Config::SetDefault("ns3::TcpL4Protocol::SocketType", StringValue(tcpVariant));
    RngSeedManager::SetSeed(randomSeed);
    RngSeedManager::SetRun(runNumber);

    std::vector<uint16_t> destinationPorts;
    destinationPorts.reserve(activeFlowCount);
    destinationPorts.push_back(destinationPort1);
    destinationPorts.push_back(destinationPort2);
    destinationPorts.push_back(destinationPort3);
    for (uint32_t index = 3; index < activeFlowCount; ++index)
    {
        destinationPorts.push_back(FIRST_DESTINATION_PORT + index);
    }
    std::sort(destinationPorts.begin(), destinationPorts.end());
    destinationPorts.resize(activeFlowCount);
    NS_ABORT_MSG_UNLESS(std::adjacent_find(destinationPorts.begin(), destinationPorts.end()) ==
                            destinationPorts.end(),
                        "Destination ports must be distinct");

    NodeContainer sourceNodes;
    sourceNodes.Create(activeFlowCount);

    NodeContainer routerNodes;
    routerNodes.Create(2);

    NodeContainer destinationNodes;
    destinationNodes.Create(activeFlowCount);

    NodeContainer allNodes;
    allNodes.Add(sourceNodes);
    allNodes.Add(routerNodes);
    allNodes.Add(destinationNodes);
    NS_ABORT_MSG_UNLESS(allNodes.GetN() == activeFlowCount * 2 + ROUTER_NODE_COUNT,
                        "Unexpected node count");

    PointToPointHelper accessLink;
    accessLink.SetDeviceAttribute("DataRate", StringValue(accessDataRate));
    accessLink.SetChannelAttribute("Delay", StringValue(accessDelay));
    accessLink.SetQueue("ns3::DropTailQueue",
                        "MaxSize",
                        StringValue(std::to_string(queueLimitPackets) + "p"));

    PointToPointHelper bottleneckLink;
    bottleneckLink.SetDeviceAttribute("DataRate", StringValue(bottleneckDataRate));
    bottleneckLink.SetChannelAttribute("Delay", StringValue(bottleneckDelay));
    bottleneckLink.SetQueue("ns3::DropTailQueue",
                            "MaxSize",
                            StringValue(std::to_string(queueLimitPackets) + "p"));

    std::vector<NetDeviceContainer> sourceAccessDevices(activeFlowCount);
    std::vector<NetDeviceContainer> destinationAccessDevices(activeFlowCount);
    for (uint32_t index = 0; index < sourceNodes.GetN(); ++index)
    {
        sourceAccessDevices[index] =
            accessLink.Install(sourceNodes.Get(index), routerNodes.Get(0));
        destinationAccessDevices[index] =
            accessLink.Install(routerNodes.Get(1), destinationNodes.Get(index));
    }
    NetDeviceContainer routerDevices =
        bottleneckLink.Install(routerNodes.Get(0), routerNodes.Get(1));

    InternetStackHelper internetStack;
    internetStack.Install(allNodes);

    Ipv4AddressHelper addressHelper;
    uint32_t assignedLinkCount = 0;
    std::vector<Ipv4Address> destinationAddresses(activeFlowCount);

    for (uint32_t index = 0; index < sourceNodes.GetN(); ++index)
    {
        addressHelper.SetBase(Ipv4Address(("10.0." + std::to_string(index + 1) + ".0").c_str()),
                              Ipv4Mask("255.255.255.0"));
        Ipv4InterfaceContainer interfaces = addressHelper.Assign(sourceAccessDevices[index]);
        NS_ABORT_MSG_UNLESS(interfaces.GetN() == 2,
                            "Each source access link must have two IPv4 interfaces");
        ++assignedLinkCount;
    }

    addressHelper.SetBase(Ipv4Address("10.0.100.0"), Ipv4Mask("255.255.255.0"));
    Ipv4InterfaceContainer bottleneckInterfaces = addressHelper.Assign(routerDevices);
    NS_ABORT_MSG_UNLESS(bottleneckInterfaces.GetN() == 2,
                        "The bottleneck link must have two IPv4 interfaces");
    ++assignedLinkCount;

    for (uint32_t index = 0; index < destinationNodes.GetN(); ++index)
    {
        addressHelper.SetBase(Ipv4Address(("10.0." + std::to_string(index + 101) + ".0").c_str()),
                              Ipv4Mask("255.255.255.0"));
        Ipv4InterfaceContainer interfaces =
            addressHelper.Assign(destinationAccessDevices[index]);
        destinationAddresses[index] = interfaces.GetAddress(1);
        NS_ABORT_MSG_UNLESS(interfaces.GetN() == 2,
                            "Each destination access link must have two IPv4 interfaces");
        ++assignedLinkCount;
    }

    NS_ABORT_MSG_UNLESS(assignedLinkCount == activeFlowCount * 2 + 1,
                        "Unexpected link count");

    Ipv4GlobalRoutingHelper::PopulateRoutingTables();
    std::vector<Ptr<DynamicQueueAssignmentDisc>> dqaQueueDiscs;
    if (dynamicQueueAssignment || fixedQueueAssignment)
    {
        TrafficControlHelper existingTrafficControl;
        existingTrafficControl.Uninstall(routerDevices);
        TrafficControlHelper dqaHelper;
        const uint32_t queueClassCount =
            hybridPerFlowState ? hybridDedicatedResources + 1 : DQA_QUEUE_CLASS_COUNT;
        const uint16_t dqaHandle =
            dqaHelper.SetRootQueueDisc("ns3::DynamicQueueAssignmentDisc",
                                       "MaxSize",
                                       StringValue(std::to_string(queueLimitPackets) + "p"),
                                       "QueueClassCount",
                                       UintegerValue(queueClassCount));
        dqaHelper.AddInternalQueues(dqaHandle,
                                    queueClassCount,
                                    "ns3::DropTailQueue<QueueDiscItem>",
                                    "MaxSize",
                                    StringValue(std::to_string(queueLimitPackets) + "p"));
        QueueDiscContainer installedDqa = dqaHelper.Install(routerDevices);
        NS_ABORT_MSG_UNLESS(installedDqa.GetN() == routerDevices.GetN(),
                            "Expected one DQA QueueDisc per bottleneck direction");
        for (uint32_t index = 0; index < installedDqa.GetN(); ++index)
        {
            Ptr<DynamicQueueAssignmentDisc> queueDisc =
                DynamicCast<DynamicQueueAssignmentDisc>(installedDqa.Get(index));
            NS_ABORT_MSG_UNLESS(queueDisc, "Installed DQA QueueDisc has an unexpected type");
            dqaQueueDiscs.push_back(queueDisc);
        }
    }

    FlowMonitorHelper flowMonitorHelper;
    Ptr<FlowMonitor> flowMonitor = flowMonitorHelper.InstallAll();

    std::vector<double> senderStartTimes(activeFlowCount, applicationStartSeconds);
    std::vector<double> senderStopTimes(activeFlowCount, applicationStopSeconds);
    if (temporaryCompetition)
    {
        for (uint32_t index = 1; index < activeFlowCount; ++index)
        {
            senderStartTimes[index] = competingFlowsStartSeconds;
            senderStopTimes[index] = competingFlowsStopSeconds;
        }
    }
    ApplicationContainer senderApplications;
    ApplicationContainer sinkApplications;
    std::vector<Ptr<PacketSink>> packetSinks;

    const bool udpWorkload = trafficModel == "udp";
    for (uint32_t index = 0; index < activeFlowCount; ++index)
    {
        Address sinkAddress(
            InetSocketAddress(Ipv4Address::GetAny(), destinationPorts[index]));
        PacketSinkHelper sinkHelper(udpWorkload ? "ns3::UdpSocketFactory"
                                                : "ns3::TcpSocketFactory",
                                    sinkAddress);
        ApplicationContainer sinkApplication = sinkHelper.Install(destinationNodes.Get(index));
        sinkApplication.Start(Seconds(sinkStartSeconds));
        sinkApplication.Stop(Seconds(simulationDurationSeconds));
        sinkApplications.Add(sinkApplication);
        packetSinks.push_back(DynamicCast<PacketSink>(sinkApplication.Get(0)));

        Address remoteAddress(
            InetSocketAddress(destinationAddresses[index], destinationPorts[index]));
        ApplicationContainer senderApplication;
        if (udpWorkload)
        {
            OnOffHelper sender("ns3::UdpSocketFactory", remoteAddress);
            sender.SetAttribute("DataRate", DataRateValue(DataRate(offeredRate)));
            sender.SetAttribute("PacketSize", UintegerValue(packetSizeBytes));
            sender.SetAttribute("OnTime",
                                StringValue("ns3::ConstantRandomVariable[Constant=1]"));
            sender.SetAttribute("OffTime",
                                StringValue("ns3::ConstantRandomVariable[Constant=0]"));
            sender.SetAttribute("MaxBytes", UintegerValue(maximumBytes));
            senderApplication = sender.Install(sourceNodes.Get(index));
        }
        else
        {
            BulkSendHelper sender("ns3::TcpSocketFactory", remoteAddress);
            sender.SetAttribute("SendSize", UintegerValue(packetSizeBytes));
            sender.SetAttribute("MaxBytes", UintegerValue(maximumBytes));
            senderApplication = sender.Install(sourceNodes.Get(index));
        }
        senderApplication.Start(Seconds(senderStartTimes[index]));
        senderApplication.Stop(Seconds(senderStopTimes[index]));
        senderApplications.Add(senderApplication);
    }

    NS_ABORT_MSG_UNLESS(senderApplications.GetN() == activeFlowCount,
                        "Expected one sender application per source");
    NS_ABORT_MSG_UNLESS(sinkApplications.GetN() == activeFlowCount,
                        "Expected one sink application per destination");

    std::vector<Ptr<Queue<Packet>>> bottleneckQueues;
    for (uint32_t index = 0; index < routerDevices.GetN(); ++index)
    {
        Ptr<PointToPointNetDevice> device =
            DynamicCast<PointToPointNetDevice>(routerDevices.Get(index));
        NS_ABORT_MSG_UNLESS(device, "Bottleneck device is not point-to-point");
        bottleneckQueues.push_back(device->GetQueue());
    }
    NS_ABORT_MSG_UNLESS(bottleneckQueues.size() == 2,
                        "Expected one queue in each bottleneck direction");

    MeasurementCollector measurements(outputDirectory,
                                     packetSinks,
                                     [&activeFlowCount]() {
                                         std::vector<std::string> ids;
                                         for (uint32_t index = 0; index < activeFlowCount; ++index)
                                         {
                                             ids.push_back("flow" + std::to_string(index + 1));
                                         }
                                         return ids;
                                     }(),
                                     bottleneckQueues,
                                     dqaQueueDiscs,
                                     hybridPerFlowState ? hybridDedicatedResources + 1
                                                        : DQA_QUEUE_CLASS_COUNT,
                                     simulationDurationSeconds,
                                     measurementIntervalSeconds,
                                     queueLimitPackets);
    NS_ABORT_MSG_UNLESS(
        bottleneckQueues[0]->TraceConnectWithoutContext(
            "Drop",
            MakeCallback(&MeasurementCollector::RecordLeftToRightDrop, &measurements)),
        "Unable to connect left-to-right queue drop trace");
    NS_ABORT_MSG_UNLESS(
        bottleneckQueues[1]->TraceConnectWithoutContext(
            "Drop",
            MakeCallback(&MeasurementCollector::RecordRightToLeftDrop, &measurements)),
        "Unable to connect right-to-left queue drop trace");

    std::unique_ptr<DqaController> dqaController;
    std::unique_ptr<HybridStateManager> hybridStateManager;
    if (dynamicQueueAssignment || fixedQueueAssignment)
    {
        const std::vector<uint16_t> activePorts = destinationPorts;
        if (hybridPerFlowState)
        {
            hybridStateManager = std::make_unique<HybridStateManager>(
                outputDirectory,
                dqaQueueDiscs,
                activePorts,
                senderStartTimes,
                senderStopTimes,
                hybridDedicatedResources,
                hybridDedicatedResources,
                simulationDurationSeconds);
            hybridStateManager->Start();
        }
        else if (dynamicQueueAssignment)
        {
            dqaController = std::make_unique<DqaController>(outputDirectory,
                                                             dqaQueueDiscs,
                                                             activePorts,
                                                             queueLimitPackets,
                                                             simulationDurationSeconds);
            dqaController->Start();
        }
        for (uint32_t direction = 0; direction < dqaQueueDiscs.size(); ++direction)
        {
            NS_ABORT_MSG_UNLESS(
                dqaQueueDiscs[direction]->TraceConnectWithoutContext(
                    "Drop",
                    direction == 0
                        ? MakeCallback(&MeasurementCollector::RecordQueueDiscLeftToRightDrop,
                                       &measurements)
                        : MakeCallback(&MeasurementCollector::RecordQueueDiscRightToLeftDrop,
                                       &measurements)),
                "Unable to connect root QueueDisc drop trace");
            const uint32_t queueClassCount =
                hybridPerFlowState ? hybridDedicatedResources + 1 : DQA_QUEUE_CLASS_COUNT;
            for (uint32_t queueIndex = 0; queueIndex < queueClassCount; ++queueIndex)
            {
                dqaQueueDiscs[direction]->GetInternalQueue(queueIndex)
                    ->TraceConnectWithoutContext(
                        "Drop",
                        direction == 0
                            ? MakeCallback(&MeasurementCollector::RecordDqaLeftToRightDrop,
                                           &measurements)
                            : MakeCallback(&MeasurementCollector::RecordDqaRightToLeftDrop,
                                           &measurements));
            }
        }
    }
    measurements.Start();

    Simulator::Stop(Seconds(simulationDurationSeconds));
    Simulator::Run();

    uint64_t totalReceivedBytes = 0;
    for (uint32_t index = 0; index < packetSinks.size(); ++index)
    {
        NS_ABORT_MSG_UNLESS(packetSinks[index],
                            "Failed to access installed packet sink application");
        const uint64_t receivedBytes = packetSinks[index]->GetTotalRx();
        NS_ABORT_MSG_UNLESS(receivedBytes > 0,
                            "A packet sink received no application bytes");
        totalReceivedBytes += receivedBytes;
        NS_LOG_UNCOND("Basic validation: flow " << (index + 1) << " received "
                                                << receivedBytes << " application bytes.");
    }
    NS_ABORT_MSG_UNLESS(totalReceivedBytes > 0,
                        "No application bytes were received by any packet sink");

    measurements.WriteFlowStatistics(flowMonitorHelper, flowMonitor,
                                     destinationPorts,
                                     udpWorkload ? 17 : 6);
    measurements.WriteDropRecords();

    const double commonIntervalSeconds = temporaryCompetition
                                             ? competingFlowsStopSeconds -
                                                   competingFlowsStartSeconds
                                             : applicationStopSeconds - applicationStartSeconds;
    double sumThroughput = 0;
    double sumSquaredThroughput = 0;
    for (const auto& sink : packetSinks)
    {
        const double throughput = sink->GetTotalRx() * 8.0 / commonIntervalSeconds;
        sumThroughput += throughput;
        sumSquaredThroughput += throughput * throughput;
    }
    const double fairness = !temporaryCompetition && sumThroughput > 0
                                ? (sumThroughput * sumThroughput) /
                                      (activeFlowCount * sumSquaredThroughput)
                                : 0;
    {
        std::ofstream metadata(outputDirectory + "/run_metadata.json");
        NS_ABORT_MSG_UNLESS(metadata, "Unable to open run metadata JSON");
        metadata << std::fixed << std::setprecision(6)
                 << "{\n"
                 << "  \"ns3_version\": \"3.48\",\n"
                 << "  \"simulation_duration_s\": " << simulationDurationSeconds << ",\n"
                 << "  \"application_start_s\": " << applicationStartSeconds << ",\n"
                 << "  \"application_stop_s\": " << applicationStopSeconds << ",\n"
                 << "  \"sink_start_s\": " << sinkStartSeconds << ",\n"
                 << "  \"temporary_competition\": "
                 << (temporaryCompetition ? "true" : "false") << ",\n"
                 << "  \"competing_flows_start_s\": " << competingFlowsStartSeconds << ",\n"
                 << "  \"competing_flows_stop_s\": " << competingFlowsStopSeconds << ",\n"
                 << "  \"flow_count\": " << activeFlowCount << ",\n"
                 << "  \"random_seed\": " << randomSeed << ",\n"
                 << "  \"run_number\": " << runNumber << ",\n"
                 << "  \"tcp_variant\": \"" << tcpVariant << "\",\n"
                 << "  \"traffic_model\": \"" << trafficModel << "\",\n"
                 << "  \"offered_rate_per_flow\": \"" << offeredRate << "\",\n"
                 << "  \"bottleneck_data_rate\": \"" << bottleneckDataRate << "\",\n"
                 << "  \"bottleneck_delay\": \"" << bottleneckDelay << "\",\n"
                 << "  \"queue_limit_packets\": " << queueLimitPackets << ",\n"
                 << "  \"dynamic_queue_assignment\": "
                 << (dynamicQueueAssignment ? "true" : "false") << ",\n"
                 << "  \"fixed_queue_assignment\": "
                 << (fixedQueueAssignment ? "true" : "false") << ",\n"
                 << "  \"dqa_queue_class_count\": "
                 << (hybridPerFlowState ? hybridDedicatedResources + 1
                                         : DQA_QUEUE_CLASS_COUNT)
                 << ",\n"
                 << "  \"hybrid_per_flow_state\": "
                 << (hybridPerFlowState ? "true" : "false") << ",\n"
                 << "  \"hybrid_dedicated_resources\": " << hybridDedicatedResources << ",\n"
                 << "  \"hybrid_fallback_queue_class\": "
                 << (hybridPerFlowState ? hybridDedicatedResources
                                        : DQA_QUEUE_CLASS_COUNT - 1)
                 << ",\n"
                 << "  \"dqa_control_interval_s\": " << DQA_CONTROL_INTERVAL_SECONDS << ",\n"
                 << "  \"dqa_switch_threshold\": " << DQA_SWITCH_THRESHOLD << ",\n"
                 << "  \"dqa_switch_cooldown_s\": " << DQA_SWITCH_COOLDOWN_SECONDS << ",\n"
                 << "  \"measurement_interval_s\": " << measurementIntervalSeconds << ",\n"
                 << "  \"physical_queue_object\": \"PointToPointNetDevice::Queue\",\n"
                 << "  \"queuedisc_aggregate_object\": \"QueueDisc::RootAggregate\",\n"
                 << "  \"logical_queue_object\": \"QueueDisc::InternalQueue\",\n"
                 << "  \"physical_drop_trace\": \"PointToPointNetDevice::Queue/Drop\",\n"
                 << "  \"internal_drop_trace\": \"QueueDisc::InternalQueue/Drop\",\n"
                 << "  \"output_directory\": \"" << outputDirectory << "\",\n"
                 << "  \"flow_monitor_layer\": \"IPv4\",\n"
                 << "  \"throughput_timestamp\": \"interval_end\",\n"
                 << "  \"fairness_index\": "
                 << (!temporaryCompetition && sumThroughput > 0
                         ? std::to_string(fairness)
                         : "null")
                 << ",\n"
                 << "  \"fairness_definition\": \"application bytes received divided by common sender interval; null for temporary competition\",\n"
                 << "  \"flow_start_times_s\": [";
        for (uint32_t index = 0; index < activeFlowCount; ++index)
        {
            metadata << (index == 0 ? "" : ",") << senderStartTimes[index];
        }
        metadata << "],\n"
                 << "  \"flow_stop_times_s\": [";
        for (uint32_t index = 0; index < activeFlowCount; ++index)
        {
            metadata << (index == 0 ? "" : ",") << senderStopTimes[index];
        }
        metadata << "],\n"
                 << "  \"run_identifier\": \""
                 << (hybridPerFlowState ? "hybrid"
                                         : dynamicQueueAssignment ? "dqa" : "baseline")
                 << "\"\n"
                 << "}\n";
    }

    Simulator::Destroy();

    NS_LOG_UNCOND("Topology simulation completed at "
                  << simulationDurationSeconds << " seconds with " << allNodes.GetN()
                  << " nodes, " << assignedLinkCount << " addressed links, and "
                  << senderApplications.GetN() << " TCP senders.");
    return 0;
}
