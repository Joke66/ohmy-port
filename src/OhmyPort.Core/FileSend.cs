using System.Text;
using OhmyPort.Core;

namespace OhmyPort.Core;

/// <summary>文件发送（下发）的内容格式。</summary>
public enum FileSendFormat
{
    /// <summary>十六进制文本（如 "01 03 0A"），解析成字节。</summary>
    HexText,

    /// <summary>文本行：每行一条命令（支持转义），逐行发送。</summary>
    TextLines,

    /// <summary>原始二进制：把文件当字节流按块发送。</summary>
    RawBinary,
}

/// <summary>
/// 文件发送的解析与分块（纯函数、无状态、可单测）。
/// 只负责「内容 → 若干字节块」，读文件与串口发送在界面层完成。
/// </summary>
public static class FileSend
{
    /// <summary>
    /// 十六进制文本 → 字节。容忍空白、逗号、分号、`0x` 前缀；含其它字符或奇数个 hex 返回 null。
    /// </summary>
    public static byte[]? ParseHexContent(string text)
    {
        text = text.Replace("0x", "", StringComparison.OrdinalIgnoreCase);
        var sb = new StringBuilder(text.Length);
        foreach (var ch in text)
        {
            if (char.IsWhiteSpace(ch) || ch is ',' or ';' or '_' or '-')
            {
                continue;
            }

            if (!Uri.IsHexDigit(ch))
            {
                return null;
            }

            sb.Append(ch);
        }

        var hex = sb.ToString();
        if (hex.Length == 0)
        {
            return [];
        }

        if (hex.Length % 2 != 0)
        {
            return null;
        }

        try
        {
            return Convert.FromHexString(hex);
        }
        catch (FormatException)
        {
            return null;
        }
    }

    /// <summary>把字节数组按固定大小分块（最后一块可能不足）。</summary>
    public static List<byte[]> Chunk(byte[] data, int chunkSize)
    {
        chunkSize = Math.Max(1, chunkSize);
        var result = new List<byte[]>((data.Length + chunkSize - 1) / chunkSize);
        for (var i = 0; i < data.Length; i += chunkSize)
        {
            var len = Math.Min(chunkSize, data.Length - i);
            result.Add(data.AsSpan(i, len).ToArray());
        }

        return result;
    }

    /// <summary>
    /// 文本行 → 逐行字节块：每行做转义解析并追加换行，空行跳过。
    /// </summary>
    public static List<byte[]> SplitTextLines(IEnumerable<string> lines, Encoding encoding, string newline)
    {
        var nl = encoding.GetBytes(newline ?? "");
        var result = new List<byte[]>();
        foreach (var raw in lines)
        {
            var line = raw.TrimEnd('\r', '\n');
            if (line.Length == 0)
            {
                continue;
            }

            var bytes = SendCodec.ParseEscaped(line, encoding);
            result.Add(nl.Length == 0 ? bytes : [.. bytes, .. nl]);
        }

        return result;
    }

    /// <summary>按格式与编码把「已读取的内容」解析成若干字节块。</summary>
    public static List<byte[]> Prepare(string content, byte[] rawBytes, FileSendFormat format,
                                       Encoding encoding, string newline, int chunkSize)
    {
        return format switch
        {
            FileSendFormat.HexText => ParseHexContent(content) is { } data
                ? Chunk(data, chunkSize)
                : [],
            FileSendFormat.TextLines => SplitTextLines(content.Split('\n'), encoding, newline),
            _ => Chunk(rawBytes, chunkSize),
        };
    }
}
