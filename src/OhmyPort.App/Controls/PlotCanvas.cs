using System.Globalization;
using System.Windows;
using System.Windows.Media;
using OhmyPort.Core;
using OhmyPort.Core.Models;

namespace OhmyPort.App.Controls;

/// <summary>
/// 实时曲线画布：按 <see cref="PlotHub"/> 里的环形缓冲直接绘制折线。
/// 自动缩放 Y 轴（窗口内极值 + 5% 余量），X 轴按容量铺满；缺失值（NaN）断线。
/// 颜色每帧从主题取，主题切换后下一次重绘即生效。
/// </summary>
public sealed class PlotCanvas : FrameworkElement
{
    /// <summary>曲线配色（深浅主题下都清晰）。</summary>
    private static readonly Color[] Palette =
    [
        Color.FromRgb(0x4F, 0xC3, 0xF7), // 蓝
        Color.FromRgb(0xFF, 0xB7, 0x4D), // 橙
        Color.FromRgb(0x81, 0xC7, 0x84), // 绿
        Color.FromRgb(0xE5, 0x73, 0x73), // 红
        Color.FromRgb(0xBA, 0x68, 0xC8), // 紫
        Color.FromRgb(0x4D, 0xD0, 0xE1), // 青
        Color.FromRgb(0xFF, 0xD5, 0x4F), // 黄
        Color.FromRgb(0xA1, 0x88, 0x7F), // 棕
    ];

    private const double LeftPad = 60;
    private const double RightPad = 12;
    private const double TopPad = 8;
    private const double BottomPad = 24;
    private const double LegendRowHeight = 18;

    public PlotHub? Hub { get; set; }

    protected override void OnRender(DrawingContext dc)
    {
        var width = ActualWidth;
        var height = ActualHeight;
        if (width <= 0 || height <= 0)
        {
            return;
        }

        var background = ThemeService.GetBrush("Brush.LogBackground");
        dc.DrawRectangle(background, null, new Rect(0, 0, width, height));

        var series = Hub?.Series.Where(s => s.Count > 0).ToList() ?? [];

        // 图例行（有曲线才占位）
        var legendHeight = series.Count > 0 ? LegendRowHeight * RowsFor(series.Count, width - LeftPad - RightPad) : 0;
        var plot = new Rect(
            LeftPad,
            TopPad + legendHeight,
            Math.Max(1, width - LeftPad - RightPad),
            Math.Max(1, height - TopPad - legendHeight - BottomPad));

        var gridBrush = MakeBrush("Brush.Border", 0x80);
        var mutedBrush = ThemeService.GetBrush("Brush.Muted");
        var pen = new Pen(gridBrush, 1);

        var range = CombinedRange(series);
        if (range is null)
        {
            DrawCentered(dc, "暂无数据（先配置提取规则，再让设备持续输出数值）", plot, mutedBrush);
            return;
        }

        var (min, max) = range.Value;
        if (max - min < 1e-9)
        {
            min -= 1;
            max += 1;
        }
        else
        {
            var pad = (max - min) * 0.05;
            min -= pad;
            max += pad;
        }

        // 横向网格 + Y 轴刻度
        const int yTicks = 4;
        for (var i = 0; i <= yTicks; i++)
        {
            var y = plot.Bottom - plot.Height * i / yTicks;
            dc.DrawLine(pen, new Point(plot.Left, y), new Point(plot.Right, y));
            var value = min + (max - min) * i / yTicks;
            var label = MakeText(TextUtil.FormatValue(value), mutedBrush, 10);
            dc.DrawText(label, new Point(plot.Left - label.Width - 6, y - label.Height / 2));
        }

        // 纵向网格
        for (var i = 0; i <= 4; i++)
        {
            var x = plot.Left + plot.Width * i / 4;
            dc.DrawLine(pen, new Point(x, plot.Top), new Point(x, plot.Bottom));
        }

        // 折线
        var capacity = Math.Max(2, Hub!.Capacity);
        foreach (var s in series)
        {
            var brush = new SolidColorBrush(Palette[SeriesColorIndex(Hub.Series, s) % Palette.Length]);
            brush.Freeze();

            var geometry = new StreamGeometry();
            using (var ctx = geometry.Open())
            {
                var started = false;
                for (var i = 0; i < s.Count; i++)
                {
                    var v = s[i];
                    if (double.IsNaN(v) || double.IsInfinity(v))
                    {
                        started = false;
                        continue;
                    }

                    var x = plot.Left + plot.Width * i / (capacity - 1);
                    var y = plot.Bottom - (v - min) / (max - min) * plot.Height;
                    var point = new Point(x, y);
                    if (!started)
                    {
                        ctx.BeginFigure(point, isFilled: false, isClosed: false);
                        started = true;
                    }
                    else
                    {
                        ctx.LineTo(point, isStroked: true, isSmoothJoin: true);
                    }
                }
            }

            geometry.Freeze();
            var linePen = new Pen(brush, 1.4);
            linePen.Freeze();
            dc.DrawGeometry(null, linePen, geometry);
        }

        // 图例：色块 + 名称 + 最新值
        DrawLegend(dc, series, mutedBrush, new Rect(LeftPad, TopPad, width - LeftPad - RightPad, legendHeight));
    }

    private static int SeriesColorIndex(IReadOnlyList<PlotSeries> all, PlotSeries target)
    {
        for (var i = 0; i < all.Count; i++)
        {
            if (ReferenceEquals(all[i], target))
            {
                return i;
            }
        }

        return 0;
    }

    private void DrawLegend(DrawingContext dc, List<PlotSeries> series, Brush textBrush, Rect area)
    {
        var x = area.Left;
        var y = area.Top + LegendRowHeight / 2;
        var maxX = area.Right;

        for (var i = 0; i < series.Count; i++)
        {
            var color = Palette[i % Palette.Length];
            var entry = MakeText(
                $"{series[i].Name} {FormatLatest(series[i].Latest)}",
                textBrush, 11, color);

            var needed = 10 + 4 + entry.Width + 14;
            if (x + needed > maxX && x > area.Left)
            {
                // 图例换行（最多两行，超出截断）
                break;
            }

            var swatchBrush = new SolidColorBrush(color);
            swatchBrush.Freeze();
            dc.DrawRectangle(swatchBrush, null, new Rect(x, y - 1.5, 10, 3));
            dc.DrawText(entry, new Point(x + 14, y - entry.Height / 2));
            x += needed;
        }
    }

    private static string FormatLatest(double? value) =>
        value is null ? "—" : TextUtil.FormatValue(value.Value);

    private static (double Min, double Max)? CombinedRange(List<PlotSeries> series)
    {
        double min = double.MaxValue;
        double max = double.MinValue;
        var any = false;
        foreach (var s in series)
        {
            var r = s.Range();
            if (r is null)
            {
                continue;
            }

            any = true;
            min = Math.Min(min, r.Value.Min);
            max = Math.Max(max, r.Value.Max);
        }

        return any ? (min, max) : null;
    }

    private static int RowsFor(int count, double width) =>
        count * 100 > width ? 2 : 1;

    /// <summary>坐标 / 图例文字用字体（西文优先，中文回退到雅黑）。</summary>
    private static readonly Typeface UiTypeface =
        new(new FontFamily("Segoe UI, Microsoft YaHei UI"), FontStyles.Normal,
            FontWeights.Normal, FontStretches.Normal);

    private FormattedText MakeText(string text, Brush brush, double size, Color? color = null)
    {
        return new FormattedText(
            text,
            CultureInfo.CurrentUICulture,
            FlowDirection.LeftToRight,
            UiTypeface,
            size,
            color is { } c ? new SolidColorBrush(c) : brush,
            VisualTreeHelper.GetDpi(this).PixelsPerDip);
    }

    private void DrawCentered(DrawingContext dc, string text, Rect area, Brush brush)
    {
        var ft = MakeText(text, brush, 12);
        dc.DrawText(ft, new Point(
            area.Left + (area.Width - ft.Width) / 2,
            area.Top + (area.Height - ft.Height) / 2));
    }

    private static Brush MakeBrush(string key, byte alpha)
    {
        if (Application.Current?.TryFindResource(key) is SolidColorBrush src)
        {
            var brush = new SolidColorBrush(Color.FromArgb(alpha, src.Color.R, src.Color.G, src.Color.B));
            brush.Freeze();
            return brush;
        }

        return Brushes.Gray;
    }
}
