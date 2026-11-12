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

    [Fact]
    public void ProtocolFields_RoundTripAndClamp()
    {
        var cfg = new AppConfig
        {
            Sessions =
            [
                new SessionConfig
                {
                    ProtocolFields =
                    [
                        new ProtocolField
                        {
                            Name = "电压",
                            Offset = 2,
                            Type = "float32",
                            BigEndian = false,
                            Scale = 0.01,
                            Bias = -5,
                            Length = 4,
                        },
                    ],
                },
            ],
        };

        var json = JsonSerializer.Serialize(cfg, AppConfig.JsonOptions);
        Assert.Contains("\"protocol_fields\"", json);
        var back = JsonSerializer.Deserialize<AppConfig>(json, AppConfig.JsonOptions)!;
        var f = back.Sessions[0].ProtocolFields[0];
        Assert.Equal("电压", f.Name);
        Assert.Equal(2, f.Offset);
        Assert.Equal("float32", f.Type);
        Assert.False(f.BigEndian);
        Assert.Equal(0.01, f.Scale);
        Assert.Equal(-5, f.Bias);

        // 非法类型 / 负偏移 / 非法系数被钳制
        var bad = new AppConfig
        {
            Sessions =
            [
                new SessionConfig
                {
                    ProtocolFields =
                    [
                        new ProtocolField { Type = "bogus", Offset = -3, Length = 0, Scale = double.NaN },
                    ],
                },
            ],
        };
        bad.Normalize();
        var bf = bad.Sessions[0].ProtocolFields[0];
        Assert.Equal("uint8", bf.Type);
        Assert.Equal(0, bf.Offset);
        Assert.Equal(1, bf.Length);
        Assert.Equal(1, bf.Scale);
    }
}
