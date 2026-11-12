using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Shapes;

namespace OhmyPort.App;

/// <summary>
/// 菜单图标附加属性：XAML 里写 <c>app:IconGlyph.Name="save"</c>，
/// 会自动按 <c>Icon.save</c> 几何生成一个跟随主题着色的图标挂到 MenuItem.Icon。
/// 对应原版 icons.py 的做法（图标单色、颜色由主题前景色注入）。
/// </summary>
public static class IconGlyph
{
    public static readonly DependencyProperty NameProperty =
        DependencyProperty.RegisterAttached(
            "Name", typeof(string), typeof(IconGlyph),
            new PropertyMetadata(null, OnNameChanged));

    public static string? GetName(DependencyObject element) =>
        (string?)element.GetValue(NameProperty);

    public static void SetName(DependencyObject element, string? value) =>
        element.SetValue(NameProperty, value);

    private static void OnNameChanged(DependencyObject element, DependencyPropertyChangedEventArgs e)
    {
        if (element is not MenuItem item || e.NewValue is not string name || name.Length == 0)
        {
            return;
        }

        if (Application.Current.TryFindResource($"Icon.{name}") is not Geometry geometry)
        {
            return;
        }

        var path = new Path
        {
            Data = geometry,
            Width = 16,
            Height = 16,
            Stretch = Stretch.Uniform,
            StrokeThickness = 1.9,
            StrokeStartLineCap = PenLineCap.Round,
            StrokeEndLineCap = PenLineCap.Round,
            StrokeLineJoin = PenLineJoin.Round,
        };
        path.SetResourceReference(Shape.StrokeProperty, "Brush.Foreground");
        item.Icon = path;
    }
}
