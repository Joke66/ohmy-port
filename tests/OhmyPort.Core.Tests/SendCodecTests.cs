using System.Text;
using OhmyPort.Core;
using Xunit;

namespace OhmyPort.Core.Tests;

public class SendCodecTests
{
    private static readonly Encoding Utf8 = SendCodec.GetEncoding("utf-8");

    [Fact]
    public void ParseHex_AcceptsSpacesAndZeroXPrefix()
    {
        Assert.Equal(new byte[] { 0x01, 0x03, 0x0A }, SendCodec.ParseHex("01 03 0A"));
        Assert.Equal(new byte[] { 0x01, 0xFF }, SendCodec.ParseHex("0x01 0xFF"));
        Assert.Empty(SendCodec.ParseHex("")!);
    }

    [Fact]
    public void ParseHex_RejectsInvalidInput()
    {
        Assert.Null(SendCodec.ParseHex("zz"));
        Assert.Null(SendCodec.ParseHex("0 1 0"));   // 奇数长度
        Assert.Null(SendCodec.ParseHex("01 0G"));
    }

    [Fact]
    public void ParseEscaped_HandlesCommonEscapes()
    {
        Assert.Equal("a\r\nb"u8.ToArray(), SendCodec.ParseEscaped(@"a\r\nb", Utf8));
        Assert.Equal(new byte[] { 0x41, 0x09, 0x42 }, SendCodec.ParseEscaped(@"A\tB", Utf8));
        Assert.Equal(new byte[] { 0x41, 0x00, 0x42 }, SendCodec.ParseEscaped(@"A\0B", Utf8));
        Assert.Equal(new byte[] { 0x41, 0x5C, 0x42 }, SendCodec.ParseEscaped(@"A\\B", Utf8));
    }

    [Fact]
    public void ParseEscaped_HandlesHexPairs()
    {
        Assert.Equal(new byte[] { 0x41, 0xFF, 0x42 }, SendCodec.ParseEscaped(@"A\xFFB", Utf8));
        Assert.Equal(new byte[] { 0x41, 0x7F }, SendCodec.ParseEscaped(@"A\x7f", Utf8));
    }

    [Fact]
    public void ParseEscaped_KeepsUnknownEscapes()
    {
        Assert.Equal("A\\aB"u8.ToArray(), SendCodec.ParseEscaped(@"A\aB", Utf8));
    }

    [Fact]
    public void ParseEscaped_EncodesTextWithCurrentEncoding()
    {
        var gbk = SendCodec.GetEncoding("gbk");
        var bytes = SendCodec.ParseEscaped("测试", gbk);
        Assert.Equal("测试", gbk.GetString(bytes));
        Assert.Equal(4, bytes.Length);   // GBK 每字 2 字节
    }

    [Fact]
    public void ParseEscaped_HandlesNonBmpCharactersAsSingleUnit()
    {
        var bytes = SendCodec.ParseEscaped("😀", Utf8);
        Assert.Equal("😀"u8.ToArray(), bytes);
    }
}
