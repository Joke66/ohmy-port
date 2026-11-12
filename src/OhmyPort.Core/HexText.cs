using System.Text;

namespace OhmyPort.Core;

/// <summary>HEX 显示格式化：每行固定字节数，右侧 ASCII 对照（不可打印字符显示为 .）。</summary>
public static class HexText
{
    public const int RowBytes = 16;

    /// <summary>把字节流按行切分，返回每行的（hex 文本, ascii 文本）。</summary>
    public static List<(string Hex, string Ascii)> Rows(ReadOnlySpan<byte> data)
    {
        var rows = new List<(string, string)>((data.Length + RowBytes - 1) / RowBytes);
        for (var i = 0; i < data.Length; i += RowBytes)
        {
            var count = Math.Min(RowBytes, data.Length - i);
            var hex = new StringBuilder(count * 3);
            var ascii = new StringBuilder(count);
            for (var k = 0; k < count; k++)
            {
                var b = data[i + k];
                if (k > 0)
                {
                    hex.Append(' ');
                }

                hex.Append(b.ToString("X2"));
                ascii.Append(b is >= 0x20 and <= 0x7E ? (char)b : '.');
            }

            rows.Add((hex.ToString(), ascii.ToString()));
        }

        return rows;
    }
}
