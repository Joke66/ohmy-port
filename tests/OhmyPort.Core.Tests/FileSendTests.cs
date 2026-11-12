using System.Text;
using OhmyPort.Core;
using Xunit;

namespace OhmyPort.Core.Tests;

public class FileSendTests
{
    private static readonly Encoding Utf8 = SendCodec.GetEncoding("utf-8");

    [Fact]
    public void ParseHexContent_AcceptsWhitespaceCommaAnd0xPrefix()
    {
        Assert.Equal(new byte[] { 0x01, 0x03, 0x0A }, FileSend.ParseHexContent("01 03 0A")!);
        Assert.Equal(new byte[] { 0x01, 0xFF }, FileSend.ParseHexContent("0x01, 0xFF")!);
        Assert.Equal(new byte[] { 0xAA, 0x55 }, FileSend.ParseHexContent("AA\n55")!);
        Assert.Equal(new byte[] { 0x01, 0x02 }, FileSend.ParseHexContent("01;02")!);
    }

    [Fact]
    public void ParseHexContent_RejectsInvalidInput()
    {
        Assert.Null(FileSend.ParseHexContent("01 0G"));
        Assert.Null(FileSend.ParseHexContent("0 1 0"));   // 奇数个 hex
        Assert.Empty(FileSend.ParseHexContent("")!);
    }

    [Fact]
    public void Chunk_SplitsEvenlyAndKeepsTail()
    {
        var data = new byte[] { 1, 2, 3, 4, 5 };
        Assert.Equal([new byte[] { 1, 2 }, new byte[] { 3, 4 }, new byte[] { 5 }],
            FileSend.Chunk(data, 2));
    }

    [Fact]
    public void SplitTextLines_AddsNewlineAndSkipsEmptyLines()
    {
        var lines = new[] { "AT", "", "AT+RESET\r\n", "\r\n" };
        var blocks = FileSend.SplitTextLines(lines, Utf8, "\r\n");

        Assert.Equal(2, blocks.Count);
        Assert.Equal("AT\r\n"u8.ToArray(), blocks[0]);
        Assert.Equal("AT+RESET\r\n"u8.ToArray(), blocks[1]);
    }

    [Fact]
    public void SplitTextLines_NoNewline_KeepsRawBytes()
    {
        var blocks = FileSend.SplitTextLines(["AB"], Utf8, "");
        Assert.Equal("AB"u8.ToArray(), blocks[0]);
    }

    [Fact]
    public void Prepare_HexText_ParsesAndChunks()
    {
        var blocks = FileSend.Prepare("01 02 03 04", [], FileSendFormat.HexText, Utf8, "", 2);
        Assert.Equal(2, blocks.Count);
        Assert.Equal(new byte[] { 0x01, 0x02 }, blocks[0]);
        Assert.Equal(new byte[] { 0x03, 0x04 }, blocks[1]);
    }

    [Fact]
    public void Prepare_RawBinary_ChunksBytes()
    {
        var blocks = FileSend.Prepare("", [1, 2, 3], FileSendFormat.RawBinary, Utf8, "", 2);
        Assert.Equal(2, blocks.Count);
    }
}
