using System.IO.Ports;
using System.Management;
using System.Text.RegularExpressions;

namespace OhmyPort.Core.Serial;

/// <summary>一个可用串口：系统名（COM3）+ 友好描述（USB-SERIAL CH340）。</summary>
public readonly record struct PortInfo(string PortName, string Description)
{
    public string Display => Description == PortName ? PortName : $"{PortName}  {Description}";

    /// <summary>下拉框 / 文本框等只认 ToString 的场合也显示友好文本，而不是 record 的字段列表。</summary>
    public override string ToString() => Display;
}

/// <summary>串口枚举：系统端口名 + WMI 友好名（对应 pyserial 的 list_ports.comports）。</summary>
public static partial class PortEnumerator
{
    [GeneratedRegex(@"\((?<name>COM\d+)\)\s*$", RegexOptions.IgnoreCase)]
    private static partial Regex CaptionPortRegex();

    /// <summary>同步枚举。WMI 首次调用可能较慢，UI 线程请用 <see cref="ListPortsAsync"/>。</summary>
    public static IReadOnlyList<PortInfo> ListPorts()
    {
        var names = SerialPort.GetPortNames()
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .OrderBy(NaturalKey)
            .ThenBy(n => n, StringComparer.OrdinalIgnoreCase)
            .ToList();

        var descriptions = QueryDescriptions();

        return names
            .Select(n => new PortInfo(n, descriptions.GetValueOrDefault(n) ?? n))
            .ToList();
    }

    /// <summary>在后台线程枚举，避免 WMI 阻塞 UI。</summary>
    public static Task<IReadOnlyList<PortInfo>> ListPortsAsync() => Task.Run(ListPorts);

    private static Dictionary<string, string> QueryDescriptions()
    {
        var map = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        try
        {
            using var searcher = new ManagementObjectSearcher(
                "SELECT Caption FROM Win32_PnPEntity WHERE Caption LIKE '%(COM%'");
            using var results = searcher.Get();
            foreach (ManagementBaseObject obj in results)
            {
                using (obj)
                {
                    if (obj["Caption"] is not string caption)
                    {
                        continue;
                    }

                    var m = CaptionPortRegex().Match(caption);
                    if (!m.Success)
                    {
                        continue;
                    }

                    var port = m.Groups["name"].Value;
                    var desc = caption[..m.Index].Trim();
                    if (desc.Length > 0)
                    {
                        map[port] = desc;
                    }
                }
            }
        }
        catch
        {
            // WMI 不可用时退回裸端口名
        }

        return map;
    }

    /// <summary>按数字自然排序：COM2 < COM10。</summary>
    private static int NaturalKey(string name) =>
        name.Length > 3 && int.TryParse(name.AsSpan(3), out var n) ? n : int.MaxValue;
}
