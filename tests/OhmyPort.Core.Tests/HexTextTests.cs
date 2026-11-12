using OhmyPort.Core;
using Xunit;

namespace OhmyPort.Core.Tests;

public class HexTextTests
{
    [Fact]
    public void Rows_SplitsInto16ByteRows()
    {
        var data = new byte[35];
        var rows = HexText.Rows(data);
        Assert.Equal(3, rows.Count);
        // 前两行各 16 字节（hex 部分 16*3-1=47 字符），第三行 3 字节
        Assert.Equal(47, rows[0].Hex.Length);
        Assert.Equal(16, rows[0].Ascii.Length);
        Assert.Equal(8, rows[2].Hex.Length);   // "00 00 00"
        Assert.Equal(3, rows[2].Ascii.Length);
    }

    [Fact]
    public void Rows_AsciiShowsPrintableAndDots()
    {
        var data = new byte[] { (byte)'A', 0x00, (byte)'B', 0x1F, (byte)'~' };
        var rows = HexText.Rows(data);
        Assert.Equal("A.B.~", rows[0].Ascii);
        Assert.Equal("41 00 42 1F 7E", rows[0].Hex);
    }

    [Fact]
    public void Rows_EmptyInput_ReturnsEmpty()
    {
        Assert.Empty(HexText.Rows([]));
    }
}
