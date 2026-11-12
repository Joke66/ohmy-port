using System.Text;

namespace OhmyPort.Core;

/// <summary>发送内容解析：HEX 字符串与转义字符（对应 Python 版 _parse_hex / _parse_escaped）。</summary>
public static class SendCodec
{
    static SendCodec() =>
        // GBK(936) 在 .NET 上需要先注册代码页提供程序
        Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);

    /// <summary>
    /// 解析 HEX 字符串，如 "01 03 0A"、"0x01 0xFF"。非法返回 null。
    /// 语义与 Python 的 bytes.fromhex 对齐：忽略空格，允许 0x 前缀。
    /// </summary>
    public static byte[]? ParseHex(string text)
    {
        var t = text.Replace(" ", "").Replace("0x", "").Replace("0X", "");
        if (t.Length % 2 != 0)
        {
            return null;
        }

        try
        {
            return Convert.FromHexString(t);
        }
        catch (FormatException)
        {
            return null;
        }
    }

    /// <summary>
    /// 解析转义字符：\r \n \t \0 \xNN \\，其余字符按给定编码编码。
    /// 未知转义（如 \a）原样保留反斜杠与后一个字符。
    /// </summary>
    public static byte[] ParseEscaped(string text, Encoding encoding)
    {
        var outBytes = new List<byte>(text.Length);
        var i = 0;
        var n = text.Length;
        while (i < n)
        {
            var c = text[i];

            // 代理对：按一个字符编码，避免把 emoji 拆成两个非法半字符
            if (char.IsHighSurrogate(c) && i + 1 < n && char.IsLowSurrogate(text[i + 1]))
            {
                outBytes.AddRange(encoding.GetBytes(text.Substring(i, 2)));
                i += 2;
                continue;
            }

            if (c == '\\' && i + 1 < n)
            {
                var next = text[i + 1];
                switch (next)
                {
                    case 'r':
                        outBytes.Add(0x0D);
                        i += 2;
                        continue;
                    case 'n':
                        outBytes.Add(0x0A);
                        i += 2;
                        continue;
                    case 't':
                        outBytes.Add(0x09);
                        i += 2;
                        continue;
                    case '0':
                        outBytes.Add(0x00);
                        i += 2;
                        continue;
                    case '\\':
                        outBytes.Add(0x5C);
                        i += 2;
                        continue;
                }

                if (next is 'x' or 'X' && i + 3 < n &&
                    byte.TryParse(text.AsSpan(i + 2, 2), System.Globalization.NumberStyles.HexNumber,
                                  System.Globalization.CultureInfo.InvariantCulture, out var hex))
                {
                    outBytes.Add(hex);
                    i += 4;
                    continue;
                }

                outBytes.AddRange(encoding.GetBytes(text.Substring(i, 2)));
                i += 2;
                continue;
            }

            outBytes.AddRange(encoding.GetBytes(c.ToString()));
            i += 1;
        }

        return [.. outBytes];
    }

    /// <summary>按配置键取编码（UTF-8 / GBK / ASCII）。</summary>
    public static Encoding GetEncoding(string key) => key switch
    {
        "gbk" => Encoding.GetEncoding(936),
        "ascii" => Encoding.ASCII,
        _ => new UTF8Encoding(encoderShouldEmitUTF8Identifier: false, throwOnInvalidBytes: false),
    };
}
