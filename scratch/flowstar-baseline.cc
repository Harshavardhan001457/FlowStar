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

#include <filesystem>
#include <fstream>
#include <iomanip>
#include <sstream>

using namespace ns3;

namespace
{

constexpr uint32_t NODE_COUNT = 8;
constexpr uint32_t LINK_COUNT = 7;
constexpr uint32_t QUEUE_LIMIT_PACKETS = 100;
constexpr double SIMULATION_DURATION_SECONDS = 20.0;
constexpr double DEFAULT_APPLICATION_START_SECONDS = 1.0;
constexpr double DEFAULT_APPLICATION_STOP_SECONDS = 19.0;
constexpr double DEFAULT_SINK_START_SECONDS = 0.5;
constexpr uint32_t DEFAULT_PACKET_SIZE_BYTES = 1000;
constexpr uint16_t FIRST_DESTINATION_PORT = 5001;
constexpr double DEFAULT_MEASUREMENT_INTERVAL_SECONDS = 0.1;

struct QueueDropRecord
{
    std::string direction;
    uint32_t packetSize;
    double timeSeconds;
};

class MeasurementCollector
{
  public:
    MeasurementCollector(const std::string& outputDirectory,
                         const std::vector<Ptr<PacketSink>>& packetSinks,
                         const std::vector<std::string>& flowIds,
                         const std::vector<Ptr<Queue<Packet>>>& bottleneckQueues,
                         double simulationDurationSeconds,
                         double samplingIntervalSeconds)
        : m_outputDirectory(outputDirectory),
          m_packetSinks(packetSinks),
          m_flowIds(flowIds),
          m_bottleneckQueues(bottleneckQueues),
          m_simulationDurationSeconds(simulationDurationSeconds),
          m_samplingIntervalSeconds(samplingIntervalSeconds),
          m_previousBytes(flowIds.size(), 0)
    {
        std::filesystem::create_directories(m_outputDirectory);
        m_throughputFile.open(m_outputDirectory + "/throughput_timeseries.csv");
        m_queueFile.open(m_outputDirectory + "/queue_timeseries.csv");
        m_dropFile.open(m_outputDirectory + "/packet_drops.csv");
        NS_ABORT_MSG_UNLESS(m_throughputFile && m_queueFile && m_dropFile,
                            "Unable to open measurement CSV files");

        m_throughputFile << "time_s,flow_id,cumulative_rx_bytes,interval_rx_bytes,"
                            "interval_throughput_bps\n";
        m_queueFile << "time_s,queue_id,occupancy_packets,occupancy_bytes,"
                       "configured_limit_packets\n";
        m_dropFile << "time_s,queue_id,trace_source,packet_size_bytes\n";
    }

    void Start()
    {
        Simulator::ScheduleNow(&MeasurementCollector::Sample, this, Seconds(0));
        Simulator::Schedule(Seconds(m_simulationDurationSeconds),
                            &MeasurementCollector::Sample,
                            this,
                            Seconds(m_simulationDurationSeconds));
    }

    void RecordDrop(const std::string& queueId, const std::string& traceSource,
                    Ptr<const Packet> packet)
    {
        m_dropRecords.push_back(
            {queueId, packet ? packet->GetSize() : 0, Simulator::Now().GetSeconds()});
        m_dropTraceSources.push_back(traceSource);
    }

    void RecordLeftToRightDrop(Ptr<const Packet> packet)
    {
        RecordDrop("left_to_right", "Drop", packet);
    }

    void RecordRightToLeftDrop(Ptr<const Packet> packet)
    {
        RecordDrop("right_to_left", "Drop", packet);
    }

    void WriteFlowStatistics(FlowMonitorHelper& flowMonitorHelper,
                             Ptr<FlowMonitor> monitor,
                             const std::vector<uint16_t>& destinationPorts)
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
                    tuple.protocol != 6)
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
                       << m_dropTraceSources[index] << ',' << record.packetSize << '\n';
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
            m_queueFile << timeSeconds << ',' << (index == 0 ? "left_to_right" : "right_to_left")
                        << ',' << m_bottleneckQueues[index]->GetNPackets() << ','
                        << m_bottleneckQueues[index]->GetNBytes() << ','
                        << QUEUE_LIMIT_PACKETS << '\n';
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
    double m_simulationDurationSeconds;
    double m_samplingIntervalSeconds;
    std::ofstream m_throughputFile;
    std::ofstream m_queueFile;
    std::ofstream m_dropFile;
    std::vector<uint64_t> m_previousBytes;
    double m_previousTimeSeconds = 0;
    bool m_havePreviousSample = false;
    std::vector<QueueDropRecord> m_dropRecords;
    std::vector<std::string> m_dropTraceSources;
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
    commandLine.Parse(argc, argv);

    NS_ABORT_MSG_UNLESS(simulationDurationSeconds > 0,
                        "Simulation duration must be greater than zero");
    NS_ABORT_MSG_UNLESS(sinkStartSeconds >= 0 &&
                            sinkStartSeconds < applicationStartSeconds &&
                            applicationStartSeconds < applicationStopSeconds &&
                            applicationStopSeconds <= simulationDurationSeconds,
                        "Application and simulation times are invalid");
    NS_ABORT_MSG_UNLESS(packetSizeBytes > 0, "Packet size must be greater than zero");
    NS_ABORT_MSG_UNLESS(measurementIntervalSeconds > 0,
                        "Measurement interval must be greater than zero");
    NS_ABORT_MSG_UNLESS(activeFlowCount >= 1 && activeFlowCount <= 3,
                        "activeFlows must be between 1 and 3");
    NS_ABORT_MSG_UNLESS(destinationPort1 != destinationPort2 &&
                            destinationPort1 != destinationPort3 &&
                            destinationPort2 != destinationPort3,
                        "Destination ports must be distinct");

    Config::SetDefault("ns3::TcpL4Protocol::SocketType", StringValue(tcpVariant));
    RngSeedManager::SetSeed(randomSeed);
    RngSeedManager::SetRun(runNumber);

    NodeContainer sourceNodes;
    sourceNodes.Create(3);

    NodeContainer routerNodes;
    routerNodes.Create(2);

    NodeContainer destinationNodes;
    destinationNodes.Create(3);

    NodeContainer allNodes;
    allNodes.Add(sourceNodes);
    allNodes.Add(routerNodes);
    allNodes.Add(destinationNodes);
    NS_ABORT_MSG_UNLESS(allNodes.GetN() == NODE_COUNT, "Unexpected node count");

    PointToPointHelper accessLink;
    accessLink.SetDeviceAttribute("DataRate", StringValue(accessDataRate));
    accessLink.SetChannelAttribute("Delay", StringValue(accessDelay));
    accessLink.SetQueue("ns3::DropTailQueue",
                        "MaxSize",
                        StringValue(std::to_string(QUEUE_LIMIT_PACKETS) + "p"));

    PointToPointHelper bottleneckLink;
    bottleneckLink.SetDeviceAttribute("DataRate", StringValue(bottleneckDataRate));
    bottleneckLink.SetChannelAttribute("Delay", StringValue(bottleneckDelay));
    bottleneckLink.SetQueue("ns3::DropTailQueue",
                            "MaxSize",
                            StringValue(std::to_string(QUEUE_LIMIT_PACKETS) + "p"));

    NetDeviceContainer sourceAccessDevices[3];
    NetDeviceContainer destinationAccessDevices[3];
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
    Ipv4Address destinationAddresses[3];

    for (uint32_t index = 0; index < sourceNodes.GetN(); ++index)
    {
        addressHelper.SetBase(Ipv4Address(("10.0." + std::to_string(index + 1) + ".0").c_str()),
                              Ipv4Mask("255.255.255.0"));
        Ipv4InterfaceContainer interfaces = addressHelper.Assign(sourceAccessDevices[index]);
        NS_ABORT_MSG_UNLESS(interfaces.GetN() == 2,
                            "Each source access link must have two IPv4 interfaces");
        ++assignedLinkCount;
    }

    addressHelper.SetBase(Ipv4Address("10.0.10.0"), Ipv4Mask("255.255.255.0"));
    Ipv4InterfaceContainer bottleneckInterfaces = addressHelper.Assign(routerDevices);
    NS_ABORT_MSG_UNLESS(bottleneckInterfaces.GetN() == 2,
                        "The bottleneck link must have two IPv4 interfaces");
    ++assignedLinkCount;

    for (uint32_t index = 0; index < destinationNodes.GetN(); ++index)
    {
        addressHelper.SetBase(Ipv4Address(("10.0." + std::to_string(index + 4) + ".0").c_str()),
                              Ipv4Mask("255.255.255.0"));
        Ipv4InterfaceContainer interfaces =
            addressHelper.Assign(destinationAccessDevices[index]);
        destinationAddresses[index] = interfaces.GetAddress(1);
        NS_ABORT_MSG_UNLESS(interfaces.GetN() == 2,
                            "Each destination access link must have two IPv4 interfaces");
        ++assignedLinkCount;
    }

    NS_ABORT_MSG_UNLESS(assignedLinkCount == LINK_COUNT, "Unexpected link count");

    Ipv4GlobalRoutingHelper::PopulateRoutingTables();
    FlowMonitorHelper flowMonitorHelper;
    Ptr<FlowMonitor> flowMonitor = flowMonitorHelper.InstallAll();

    const uint16_t destinationPorts[] = {destinationPort1, destinationPort2, destinationPort3};
    ApplicationContainer senderApplications;
    ApplicationContainer sinkApplications;
    std::vector<Ptr<PacketSink>> packetSinks;

    for (uint32_t index = 0; index < activeFlowCount; ++index)
    {
        Address sinkAddress(
            InetSocketAddress(Ipv4Address::GetAny(), destinationPorts[index]));
        PacketSinkHelper sinkHelper("ns3::TcpSocketFactory", sinkAddress);
        ApplicationContainer sinkApplication = sinkHelper.Install(destinationNodes.Get(index));
        sinkApplication.Start(Seconds(sinkStartSeconds));
        sinkApplication.Stop(Seconds(simulationDurationSeconds));
        sinkApplications.Add(sinkApplication);
        packetSinks.push_back(DynamicCast<PacketSink>(sinkApplication.Get(0)));

        Address remoteAddress(
            InetSocketAddress(destinationAddresses[index], destinationPorts[index]));
        BulkSendHelper sender("ns3::TcpSocketFactory", remoteAddress);
        sender.SetAttribute("SendSize", UintegerValue(packetSizeBytes));
        sender.SetAttribute("MaxBytes", UintegerValue(maximumBytes));
        ApplicationContainer senderApplication = sender.Install(sourceNodes.Get(index));
        senderApplication.Start(Seconds(applicationStartSeconds));
        senderApplication.Stop(Seconds(applicationStopSeconds));
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
                                     {"flow1", "flow2", "flow3"},
                                     bottleneckQueues,
                                     simulationDurationSeconds,
                                     measurementIntervalSeconds);
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
                                     std::vector<uint16_t>(destinationPorts,
                                                           destinationPorts + activeFlowCount));
    measurements.WriteDropRecords();

    const double commonIntervalSeconds = applicationStopSeconds - applicationStartSeconds;
    double sumThroughput = 0;
    double sumSquaredThroughput = 0;
    for (const auto& sink : packetSinks)
    {
        const double throughput = sink->GetTotalRx() * 8.0 / commonIntervalSeconds;
        sumThroughput += throughput;
        sumSquaredThroughput += throughput * throughput;
    }
    const double fairness = sumThroughput > 0
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
                 << "  \"flow_count\": " << activeFlowCount << ",\n"
                 << "  \"random_seed\": " << randomSeed << ",\n"
                 << "  \"run_number\": " << runNumber << ",\n"
                 << "  \"tcp_variant\": \"" << tcpVariant << "\",\n"
                 << "  \"bottleneck_data_rate\": \"" << bottleneckDataRate << "\",\n"
                 << "  \"bottleneck_delay\": \"" << bottleneckDelay << "\",\n"
                 << "  \"queue_limit_packets\": " << QUEUE_LIMIT_PACKETS << ",\n"
                 << "  \"measurement_interval_s\": " << measurementIntervalSeconds << ",\n"
                 << "  \"output_directory\": \"" << outputDirectory << "\",\n"
                 << "  \"flow_monitor_layer\": \"IPv4\",\n"
                 << "  \"throughput_timestamp\": \"interval_end\",\n"
                 << "  \"fairness_index\": " << (sumThroughput > 0 ? std::to_string(fairness)
                                                                    : "null")
                 << ",\n"
                 << "  \"fairness_definition\": \"application bytes received divided by common sender interval\",\n"
                 << "  \"run_identifier\": \"baseline\"\n"
                 << "}\n";
    }

    Simulator::Destroy();

    NS_LOG_UNCOND("Topology simulation completed at "
                  << simulationDurationSeconds << " seconds with " << allNodes.GetN()
                  << " nodes, " << assignedLinkCount << " addressed links, and "
                  << senderApplications.GetN() << " TCP senders.");
    return 0;
}
