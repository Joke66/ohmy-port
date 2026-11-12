using System.Text.Json;
using OhmyPort.Core.Models;
using Xunit;

namespace OhmyPort.Core.Tests;

public class AppConfigTests
{
    [Fact]
    public void NewSessionFields_RoundTripThroughJson()
    {
        var cfg = new AppConfig
        {
            Sessions =
            [
                new SessionConfig
                {
                    Port = "COM3",
                    SendChecksum = "crc16_modbus",
                    FrameEnabled = true,
                    FrameHeader = "AA 55",
                    FrameTail = "0D 0A",
                    FrameLengthSize = 1,
                    FrameLengthBase = 0,
                    FrameBigEndian = false,
                    FrameChecksum = "sum8",
                },
            ],
        };

        var json = JsonSerializer.Serialize(cfg, AppConfig.JsonOptions);
        var back = JsonSerializer.Deserialize<AppConfig>(json, AppConfig.JsonOptions)!;
        var s = back.Sessions[0];

        Assert.Equal("crc16_modbus", s.SendChecksum);
        Assert.True(s.FrameEnabled);
        Assert.Equal("AA 55", s.FrameHeader);
        Assert.Equal("0D 0A", s.FrameTail);
        Assert.Equal(1, s.FrameLengthSize);
        Assert.Equal(0, s.FrameLengthBase);
        Assert.False(s.FrameBigEndian);
        Assert.Equal("sum8", s.FrameChecksum);
    }

    [Fact]
    public void Normalize_ClampsInvalidChecksumAndLength()
    {
        var cfg = new AppConfig
        {
            Sessions =
            [
                new SessionConfig
                {
                    SendChecksum = "crc32",
                    FrameChecksum = "bogus",
                    FrameLengthSize = 3,
                    FrameLengthBase = 999999,
                },
            ],
        };
        cfg.Normalize();
        var s = cfg.Sessions[0];

        Assert.Equal("none", s.SendChecksum);
        Assert.Equal("none", s.FrameChecksum);
        Assert.Equal(0, s.FrameLengthSize);
        Assert.Equal(65536, s.FrameLengthBase);
    }
}
