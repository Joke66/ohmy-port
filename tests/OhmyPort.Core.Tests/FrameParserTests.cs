using OhmyPort.Core.Serial;
using Xunit;

namespace OhmyPort.Core.Tests;

public class FrameParserTests
{
    private static void AssertFrames(List<Frame> actual, params (byte[] Data, bool Ok)[] expected)
    {
        Assert.Equal(expected.Length, actual.Count);
        for (var i = 0; i < expected.Length; i++)
        {
            Assert.Equal(expected[i].Data, actual[i].Data);
            Assert.Equal(expected[i].Ok, actual[i].ChecksumOk);
        }
    }

    [Fact]
    public void HeaderAndTail()
    {
        var p = new FrameParser { Header = [0xAA, 0x55], Tail = [0x0D, 0x0A] };
        var outFrames = p.Feed([0xAA, 0x55, 0x01, 0x02, 0x0D, 0x0A]);
        AssertFrames(outFrames, ([0xAA, 0x55, 0x01, 0x02, 0x0D, 0x0A], true));
    }

    [Fact]
    public void LengthField()
    {
        // 帧头 AA，长度字段 1 字节紧跟其后，数据长度 2
        var p = new FrameParser { Header = [0xAA], LengthSize = 1 };
        var outFrames = p.Feed([0xAA, 0x02, 0x01, 0x02]);
        AssertFrames(outFrames, ([0xAA, 0x02, 0x01, 0x02], true));
    }

    [Fact]
    public void FragmentedInput_EmitsOnlyWhenComplete()
    {
        var p = new FrameParser { Header = [0xAA, 0x55], Tail = [0x0D, 0x0A] };
        Assert.Empty(p.Feed([0xAA]));
        Assert.Empty(p.Feed([0x55, 0x01]));
        var outFrames = p.Feed([0x02, 0x0D, 0x0A]);
        AssertFrames(outFrames, ([0xAA, 0x55, 0x01, 0x02, 0x0D, 0x0A], true));
    }

    [Fact]
    public void Sum8_ChecksAndReportsFailure()
    {
        var p = new FrameParser { LengthSize = 1, Checksum = ChecksumKind.Sum8 };
        byte[] good = [3, 1, 2, 3, 9];
        AssertFrames(p.Feed(good), (good, true));

        var p2 = new FrameParser { LengthSize = 1, Checksum = ChecksumKind.Sum8 };
        byte[] bad = [3, 1, 2, 3, 7];
        AssertFrames(p2.Feed(bad), (bad, false));
    }

    [Fact]
    public void Xor8()
    {
        // 覆盖 [3,1,2,3]，xor = 3^1^2^3 = 3
        var p = new FrameParser { LengthSize = 1, Checksum = ChecksumKind.Xor8 };
        byte[] good = [3, 1, 2, 3, 3];
        AssertFrames(p.Feed(good), (good, true));
    }

    [Fact]
    public void Crc16Modbus()
    {
        byte[] data = [0x01, 0x03, 0x00, 0x00, 0x00, 0x0A];
        var covered = new byte[] { 6 }.Concat(data).ToArray();
        var crc = FrameParser.Crc16Modbus(covered);
        byte[] crcBytes = [(byte)(crc & 0xFF), (byte)(crc >> 8)];

        var p = new FrameParser { LengthSize = 1, Checksum = ChecksumKind.Crc16Modbus };
        var frame = new byte[] { 6 }.Concat(data).Concat(crcBytes).ToArray();
        AssertFrames(p.Feed(frame), (frame, true));
    }

    [Fact]
    public void CorruptedCrc_ReportsFailure()
    {
        var p = new FrameParser { LengthSize = 1, Checksum = ChecksumKind.Crc16Modbus };
        var frame = new byte[] { 6, 0x01, 0x03, 0x00, 0x00, 0x00, 0x0A, 0x00, 0x00 };
        AssertFrames(p.Feed(frame), (frame, false));
    }
}
