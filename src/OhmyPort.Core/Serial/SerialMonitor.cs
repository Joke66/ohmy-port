using System.IO.Ports;
using OhmyPort.Core;

namespace OhmyPort.Core.Serial;

/// <summary>串口连接参数。</summary>
public sealed record SerialSettings(
    string PortName,
    int BaudRate,
    int DataBits = 8,
    Parity Parity = Parity.None,
    StopBits StopBits = StopBits.One,
    Handshake Handshake = Handshake.None);

/// <summary>
/// 串口后端：独立线程接收，通过事件把数据抛给上层（UI 只做队列消费）。
/// 对应 Python 版 serial_worker.SerialMonitor。
/// </summary>
public sealed class SerialMonitor : IDisposable
{
    private readonly object _gate = new();
    private readonly ManualResetEventSlim _stopping = new(false);
    private SerialPort? _port;
    private Thread? _thread;
    private FrameParser? _frameParser;

    public long RxBytes;
    public string LastError { get; private set; } = "";

    /// <summary>收到数据时触发（在接收线程上），参数为本次切出的行/帧。</summary>
    public event Action<IReadOnlyList<Frame>>? Received;

    public bool IsConnected
    {
        get
        {
            lock (_gate)
            {
                return _port is { IsOpen: true };
            }
        }
    }

    /// <summary>设置帧解析器后按帧切分；置 null 恢复按行切分。</summary>
    public void SetFrameParser(FrameParser? parser) => _frameParser = parser;

    public bool Connect(SerialSettings settings)
    {
        Disconnect();

        try
        {
            var port = new SerialPort(settings.PortName, settings.BaudRate, settings.Parity,
                                      settings.DataBits, settings.StopBits)
            {
                Handshake = settings.Handshake,
                ReadTimeout = 100,
                WriteTimeout = 1000,
            };
            port.Open();

            lock (_gate)
            {
                _port = port;
            }
        }
        catch (Exception ex)
        {
            LastError = ex.Message;
            return false;
        }

        LastError = "";
        _stopping.Reset();
        _thread = new Thread(ReceiveLoop)
        {
            IsBackground = true,
            Name = "OhmyPort.Receive",
        };
        _thread.Start();
        return true;
    }

    public void Disconnect()
    {
        _stopping.Set();

        SerialPort? port;
        Thread? thread;
        lock (_gate)
        {
            port = _port;
            thread = _thread;
            _port = null;
            _thread = null;
        }

        try
        {
            port?.Close();
        }
        catch
        {
            // 关闭时的异常无需上报
        }

        if (thread is not null && thread.IsAlive && thread != Thread.CurrentThread)
        {
            thread.Join(TimeSpan.FromSeconds(1));
        }

        port?.Dispose();
    }

    public bool Send(ReadOnlySpan<byte> data)
    {
        SerialPort? port;
        lock (_gate)
        {
            port = _port;
        }

        if (port is null || !port.IsOpen)
        {
            return false;
        }

        try
        {
            port.Write(data.ToArray(), 0, data.Length);
            return true;
        }
        catch
        {
            return false;
        }
    }

    public void SetDtr(bool value)
    {
        try
        {
            lock (_gate)
            {
                if (_port is not null)
                {
                    _port.DtrEnable = value;
                }
            }
        }
        catch
        {
            // 部分虚拟串口不支持 DTR
        }
    }

    public void SetRts(bool value)
    {
        try
        {
            lock (_gate)
            {
                if (_port is not null)
                {
                    _port.RtsEnable = value;
                }
            }
        }
        catch
        {
            // 部分虚拟串口不支持 RTS
        }
    }

    private void ReceiveLoop()
    {
        var chunk = new byte[UiDefaults.ReadChunk];
        var lineBuf = new List<byte>(UiDefaults.ReadChunk * 2);
        var frames = new List<Frame>(64);

        while (!_stopping.IsSet)
        {
            SerialPort? port;
            lock (_gate)
            {
                port = _port;
            }

            if (port is null || !port.IsOpen)
            {
                break;
            }

            int read;
            try
            {
                read = port.Read(chunk, 0, chunk.Length);
            }
            catch (TimeoutException)
            {
                continue;
            }
            catch
            {
                if (_stopping.IsSet)
                {
                    break;
                }

                Thread.Sleep(20);
                continue;
            }

            if (read <= 0)
            {
                continue;
            }

            Interlocked.Add(ref RxBytes, read);
            frames.Clear();

            var parser = _frameParser;
            if (parser is not null)
            {
                frames.AddRange(parser.Feed(chunk.AsSpan(0, read)));
            }
            else
            {
                SplitLines(chunk.AsSpan(0, read), lineBuf, frames);
            }

            if (frames.Count > 0)
            {
                try
                {
                    Received?.Invoke(frames);
                }
                catch
                {
                    // 上层回调异常不能中断接收线程
                }
            }
        }
    }

    private static void SplitLines(ReadOnlySpan<byte> chunk, List<byte> lineBuf, List<Frame> frames)
    {
        foreach (var b in chunk)
        {
            lineBuf.Add(b);
        }

        var start = 0;
        for (var i = 0; i < lineBuf.Count; i++)
        {
            if (lineBuf[i] != (byte)'\n')
            {
                continue;
            }

            var len = i - start;
            if (len > 0 && lineBuf[i - 1] == (byte)'\r')
            {
                len--;
            }

            var payload = new byte[len];
            for (var k = 0; k < len; k++)
            {
                payload[k] = lineBuf[start + k];
            }

            frames.Add(new Frame(payload, true));
            start = i + 1;
        }

        if (start > 0)
        {
            lineBuf.RemoveRange(0, start);
        }
    }

    public void Dispose() => Disconnect();
}
