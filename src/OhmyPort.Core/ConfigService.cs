using System.Text.Json;
using OhmyPort.Core.Models;

namespace OhmyPort.Core;

/// <summary>配置读写（对应 Python 版 _load_config / _save_config / _config_data）。</summary>
public sealed class ConfigService
{
    private readonly string _path;

    public ConfigService(string? path = null) => _path = path ?? AppPaths.ConfigPath;

    public string Path => _path;

    /// <summary>读取配置；文件不存在或损坏时返回默认配置。</summary>
    public AppConfig Load()
    {
        try
        {
            if (!File.Exists(_path))
            {
                return new AppConfig();
            }

            var json = File.ReadAllText(_path);
            var config = JsonSerializer.Deserialize<AppConfig>(json, AppConfig.JsonOptions) ?? new AppConfig();
            config.Normalize();
            return config;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or JsonException)
        {
            return new AppConfig();
        }
    }

    public bool Save(AppConfig config)
    {
        try
        {
            var dir = System.IO.Path.GetDirectoryName(_path);
            if (!string.IsNullOrEmpty(dir))
            {
                Directory.CreateDirectory(dir);
            }

            File.WriteAllText(_path, JsonSerializer.Serialize(config, AppConfig.JsonOptions));
            return true;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return false;
        }
    }
}
