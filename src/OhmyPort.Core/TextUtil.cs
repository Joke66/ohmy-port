using System.Globalization;
using System.Text.RegularExpressions;

namespace OhmyPort.Core;

/// <summary>纯文本工具：格式化、数字提取、版本比较。</summary>
public static partial class TextUtil
{
    private static readonly CultureInfo Inv = CultureInfo.InvariantCulture;

    [GeneratedRegex(@"-?\d+\.?\d*")]
    private static partial Regex NumberRegex();

    [GeneratedRegex(@"(\d+)\.(\d+)\.(\d+)")]
    private static partial Regex VersionRegex();

    /// <summary>字节数的人类可读形式：512 B / 2.0 KB / 3.0 MB。</summary>
    public static string FormatBytes(long n)
    {
        if (n < 1024)
        {
            return $"{n} B";
        }

        if (n < 1024 * 1024)
        {
            return (n / 1024.0).ToString("F1", Inv) + " KB";
        }

        return (n / 1024.0 / 1024.0).ToString("F1", Inv) + " MB";
    }

    /// <summary>提取文本中的全部数字（含负号与小数）。</summary>
    public static List<double> ExtractNumbers(string text)
    {
        var result = new List<double>();
        foreach (Match m in NumberRegex().Matches(text))
        {
            if (double.TryParse(m.Value, NumberStyles.Float, Inv, out var v))
            {
                result.Add(v);
            }
        }

        return result;
    }

    /// <summary>绘图数值格式：整数不带小数点，小数最多 4 位并去掉尾零。</summary>
    public static string FormatValue(double v)
    {
        if (!double.IsNaN(v) && !double.IsInfinity(v) && v == Math.Floor(v))
        {
            return ((long)v).ToString(Inv);
        }

        return v.ToString("F4", Inv).TrimEnd('0').TrimEnd('.');
    }

    /// <summary>从任意字符串里取 x.y.z 版本号；取不到返回空数组。</summary>
    public static int[] ParseVersion(string? text)
    {
        var m = VersionRegex().Match(text ?? "");
        if (!m.Success)
        {
            return [];
        }

        return
        [
            int.Parse(m.Groups[1].Value, Inv),
            int.Parse(m.Groups[2].Value, Inv),
            int.Parse(m.Groups[3].Value, Inv),
        ];
    }

    /// <summary>版本比较：a 大于 b 返回正数。</summary>
    public static int CompareVersions(int[] a, int[] b)
    {
        return a.AsSpan().SequenceCompareTo(b.AsSpan());
    }
}
