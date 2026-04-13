using System;
using System.Net;
using System.Net.Sockets;
using System.Text.Json;

namespace DFE.Indexer.Services;

/// <summary>Sends a one-way UDP datagram to the Python UI to trigger an index refresh.</summary>
public sealed class UdpNotifier : IDisposable
{
    private readonly UdpClient _udp = new();
    private readonly IPEndPoint _endpoint;

    public UdpNotifier(int port)
    {
        _endpoint = new IPEndPoint(IPAddress.Loopback, port);
    }

    public void Send(int changedCount)
    {
        try
        {
            byte[] payload = JsonSerializer.SerializeToUtf8Bytes(
                new { @event = "index_updated", count = changedCount });
            _udp.Send(payload, _endpoint);
        }
        catch (SocketException)
        {
            // Python listener not running — silently ignore
        }
    }

    public void Dispose() => _udp.Dispose();
}
