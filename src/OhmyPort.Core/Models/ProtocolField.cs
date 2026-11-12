using System.Buffers.Binary;
using System.Text;
using OhmyPort.Core;

namespace OhmyPort.Core.Models;

/// <summary>字段数据类型配置键（与 JSON / 下拉框共用，避免字符串漂移）。</summary>
public static class FieldTypes
{
    public const string UInt8 = "uint8";
    public const string Int8 = "int8";
    public const string UInt16 = "uint16";
    public const string Int16 = "int16";
    public const string UInt32 = "uint32";
    public const string Int32 = "int32";
    public const string Float32 = "float32";
    public const string Float64 = "float64";
    public const string HexBytes = "hex";
    public const string Ascii = "ascii";

    /// <summary>下拉框选项：显示名 / 配置键 / 固定字节数（0 表示由字段 Length 决定）。</summary>
    public static readonly (string Label, string Key, int Size)[] All =
    [
        ("uint8", UInt8, 1),
        ("int8", Int8, 1),
        ("uint16", UInt16, 2),
        ("int16", Int16, 2),
        ("uint32", UInt32, 4),
        ("int32", Int32, 4),
        ("float32", Float32, 4),
        ("float64", Float64, 8),
        ("hex", HexBytes, 0),
        ("ascii", Ascii, 0),
    ];

    public static bool IsValid(string? key) => All.Any(t => t.Key == key);

    /// <summary>固定字节数；hex / ascii 返回 0（需用字段 Length）。</summary>
    public static int SizeOf(string? key) =>
        All.FirstOrDefault(t => t.Key == key).Size;

    public static string LabelOf(string? key) =>
        All.FirstOrDefault(t => t.Key == key).Label ?? key ?? "";
}

/// <summary>
/// 单条协议字段定义：在帧内从某偏移处按类型取值。
/// 偏移相对「数据区起始」（帧头 + 长度字段之后），与帧头长度无关，改帧头不会打乱字段。
/// </summary>
public sealed class ProtocolField
{
    public string Name { get; set; } = "";

    /// <summary>相对数据区起始的字节偏移。</summary>
    public int Offset { get; set; }

    /// <summary>类型键（见 <see cref="FieldTypes"/>）。</summary>
    public string Type { get; set; } = FieldTypes.UInt8;

    /// <summary>多字节字段的字节序；hex / ascii 不适用。</summary>
    public bool BigEndian { get; set; } = true;

    /// <summary>物理值 = 原始值 * Scale + Bias（缩放系数与零点偏移）。</summary>
    public double Scale { get; set; } = 1;

    public double Bias { get; set; }

    /// <summary>hex / ascii 类型的字节数（其它类型忽略）。</summary>
    public int Length { get; set; } = 1;
}

/// <summary>一个字段的解析结果。</summary>
public readonly record struct FieldValue(string Name, string TypeLabel, string Text, string RawHex, bool Ok);

/// <summary>
/// 协议字段解析：把一帧按字段定义解成「名称 | 类型 | 值」。
/// 纯函数、无状态，可单测。
/// </summary>
public static class ProtocolDecoder
{
    /// <summary>
    /// 解析一帧。<paramref name="offsetBase"/> 为数据区在帧内的起始下标（帧头 + 长度字段长度）。
    /// 字段越界或类型非法时该行 <see cref="FieldValue.Ok"/> 为 false，值显示为「—」。
    /// </summary>
    public static List<FieldValue> Decode(ReadOnlySpan<byte> frame, int offsetBase,
                                          IReadOnlyList<ProtocolField> fields)
    {
        var result = new List<FieldValue>(fields.Count);
        foreach (var field in fields)
        {
            result.Add(DecodeOne(frame, offsetBase, field));
        }

        return result;
    }

    private static FieldValue DecodeOne(ReadOnlySpan<byte> frame, int offsetBase, ProtocolField field)
    {
        var label = FieldTypes.LabelOf(field.Type);
        var size = FieldTypes.SizeOf(field.Type);
        var isRaw = field.Type is FieldTypes.HexBytes or FieldTypes.Ascii;
        if (isRaw)
        {
            size = field.Length;
        }

        var start = offsetBase + field.Offset;
        if (size <= 0 || start < 0 || start + size > frame.Length)
        {
            return new FieldValue(field.Name, label, "—", "", false);
        }

        var slice = frame.Slice(start, size);
        var rawHex = ToHex(slice);

        if (field.Type == FieldTypes.HexBytes)
        {
            return new FieldValue(field.Name, label, rawHex, rawHex, true);
        }

        if (field.Type == FieldTypes.Ascii)
        {
            var text = Encoding.ASCII.GetString(slice.ToArray()).TrimEnd('\0');
            return new FieldValue(field.Name, label, text, rawHex, true);
        }

        if (!TryNumeric(slice, field.Type, field.BigEndian, out var raw))
        {
            return new FieldValue(field.Name, label, "—", rawHex, false);
        }

        var value = raw * field.Scale + field.Bias;
        return new FieldValue(field.Name, label, TextUtil.FormatValue(value), rawHex, true);
    }

    private static bool TryNumeric(ReadOnlySpan<byte> data, string type, bool bigEndian, out double value)
    {
        value = 0;
        switch (type)
        {
            case FieldTypes.UInt8:
                value = data[0];
                return true;
            case FieldTypes.Int8:
                value = (sbyte)data[0];
                return true;
            case FieldTypes.UInt16:
                value = bigEndian
                    ? BinaryPrimitives.ReadUInt16BigEndian(data)
                    : BinaryPrimitives.ReadUInt16LittleEndian(data);
                return true;
            case FieldTypes.Int16:
                value = bigEndian
                    ? BinaryPrimitives.ReadInt16BigEndian(data)
                    : BinaryPrimitives.ReadInt16LittleEndian(data);
                return true;
            case FieldTypes.UInt32:
                value = bigEndian
                    ? BinaryPrimitives.ReadUInt32BigEndian(data)
                    : BinaryPrimitives.ReadUInt32LittleEndian(data);
                return true;
            case FieldTypes.Int32:
                value = bigEndian
                    ? BinaryPrimitives.ReadInt32BigEndian(data)
                    : BinaryPrimitives.ReadInt32LittleEndian(data);
                return true;
            case FieldTypes.Float32:
                var f = bigEndian
                    ? BinaryPrimitives.ReadInt32BigEndian(data)
                    : BinaryPrimitives.ReadInt32LittleEndian(data);
                value = BitConverter.Int32BitsToSingle(f);
                return true;
            case FieldTypes.Float64:
                var d = bigEndian
                    ? BinaryPrimitives.ReadInt64BigEndian(data)
                    : BinaryPrimitives.ReadInt64LittleEndian(data);
                value = BitConverter.Int64BitsToDouble(d);
                return true;
            default:
                return false;
        }
    }

    private static string ToHex(ReadOnlySpan<byte> data)
    {
        var sb = new StringBuilder(data.Length * 3);
        foreach (var b in data)
        {
            if (sb.Length > 0)
            {
                sb.Append(' ');
            }

            sb.Append(b.ToString("X2"));
        }

        return sb.ToString();
    }
}
