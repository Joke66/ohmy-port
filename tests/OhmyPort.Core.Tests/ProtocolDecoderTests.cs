using OhmyPort.Core.Models;
using Xunit;

namespace OhmyPort.Core.Tests;

public class ProtocolDecoderTests
{
    private static ProtocolField F(string name, int offset, string type,
                                   bool bigEndian = true, double scale = 1, double bias = 0, int length = 1) =>
        new()
        {
            Name = name,
            Offset = offset,
            Type = type,
            BigEndian = bigEndian,
            Scale = scale,
            Bias = bias,
            Length = length,
        };

    [Fact]
    public void UInt16_BigAndLittleEndian()
    {
        byte[] frame = [0x12, 0x34];

        var be = ProtocolDecoder.Decode(frame, 0, [F("v", 0, FieldTypes.UInt16)]);
        var le = ProtocolDecoder.Decode(frame, 0, [F("v", 0, FieldTypes.UInt16, bigEndian: false)]);

        Assert.Equal("4660", be[0].Text);   // 0x1234
        Assert.Equal("13330", le[0].Text);  // 0x3412
        Assert.True(be[0].Ok);
    }

    [Fact]
    public void Int8_NegativeValue()
    {
        var r = ProtocolDecoder.Decode([0xFF], 0, [F("t", 0, FieldTypes.Int8)]);
        Assert.Equal("-1", r[0].Text);
    }

    [Fact]
    public void Int16_LittleEndian_Negative()
    {
        var r = ProtocolDecoder.Decode([0xFE, 0xFF], 0, [F("t", 0, FieldTypes.Int16, bigEndian: false)]);
        Assert.Equal("-2", r[0].Text);
    }

    [Fact]
    public void Float32_BigEndian()
    {
        // 3.14f 的大端字节序
        var frame = new byte[] { 0x40, 0x48, 0xF5, 0xC3 };
        var r = ProtocolDecoder.Decode(frame, 0, [F("f", 0, FieldTypes.Float32)]);
        Assert.True(r[0].Ok);
        Assert.Equal("3.14", r[0].Text);
    }

    [Fact]
    public void Float64_LittleEndian()
    {
        var bytes = BitConverter.GetBytes(1.5d);
        if (!BitConverter.IsLittleEndian)
        {
            Array.Reverse(bytes);
        }

        var r = ProtocolDecoder.Decode(bytes, 0, [F("d", 0, FieldTypes.Float64, bigEndian: false)]);
        Assert.Equal("1.5", r[0].Text);
    }

    [Fact]
    public void ScaleAndBias_ApplyToRawValue()
    {
        // 原始 1234（0x04D2），系数 0.1 → 123.4
        var r = ProtocolDecoder.Decode([0x04, 0xD2], 0,
            [F("v", 0, FieldTypes.UInt16, scale: 0.1)]);
        Assert.Equal("123.4", r[0].Text);

        // 零点偏移：原始 100 → 100 - 50 = 50
        var r2 = ProtocolDecoder.Decode([100], 0, [F("t", 0, FieldTypes.UInt8, bias: -50)]);
        Assert.Equal("50", r2[0].Text);
    }

    [Fact]
    public void OffsetBase_ShiftsFieldOrigin()
    {
        // 数据区从下标 2 开始，字段偏移 0 落到帧下标 2
        var r = ProtocolDecoder.Decode([0xAA, 0x55, 0x07, 0x00], 2, [F("v", 0, FieldTypes.UInt8)]);
        Assert.Equal("7", r[0].Text);
    }

    [Fact]
    public void OutOfRange_ReturnsNotOk()
    {
        var r = ProtocolDecoder.Decode([0x01], 0, [F("v", 0, FieldTypes.UInt16)]);
        Assert.False(r[0].Ok);
        Assert.Equal("—", r[0].Text);
    }

    [Fact]
    public void HexAndAscii_UseFieldLength()
    {
        byte[] frame = [0x01, 0x02, 0x03, (byte)'O', (byte)'K', 0x00];

        var hex = ProtocolDecoder.Decode(frame, 0, [F("h", 0, FieldTypes.HexBytes, length: 3)]);
        var ascii = ProtocolDecoder.Decode(frame, 0, [F("s", 3, FieldTypes.Ascii, length: 3)]);

        Assert.Equal("01 02 03", hex[0].Text);
        Assert.Equal("OK", ascii[0].Text);
    }

    [Fact]
    public void RawHex_AlwaysReportsSourceBytes()
    {
        var r = ProtocolDecoder.Decode([0xAA, 0x55], 0, [F("v", 0, FieldTypes.UInt16)]);
        Assert.Equal("AA 55", r[0].RawHex);
    }

    [Fact]
    public void SizeOf_ReportsTypeWidth()
    {
        Assert.Equal(1, FieldTypes.SizeOf(FieldTypes.UInt8));
        Assert.Equal(4, FieldTypes.SizeOf(FieldTypes.Float32));
        Assert.Equal(8, FieldTypes.SizeOf(FieldTypes.Float64));
        Assert.Equal(0, FieldTypes.SizeOf(FieldTypes.HexBytes));
    }
}
