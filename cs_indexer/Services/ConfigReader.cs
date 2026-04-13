using System;
using System.IO;
using System.Text.Json;

namespace DFE.Indexer.Services;

/// <summary>
/// Mirrors Python's ConfigManager portable/standard mode detection.
/// Portable: config.json next to the executable.
/// Standard: %LOCALAPPDATA%\SHL\DualPaneFileManager\config.json
/// </summary>
public static class ConfigReader
{
    private const string OrgPath = @"SHL\DualPaneFileManager";
    private const string ConfigFileName = "config.json";

    public static string? DefaultScanRoot { get; private set; }
    public static string? IndexDirectory { get; private set; }

    public static bool TryLoad()
    {
        string configPath = ResolveConfigPath();
        if (!File.Exists(configPath))
            return false;

        try
        {
            using var stream = File.OpenRead(configPath);
            using var doc = JsonDocument.Parse(stream);
            var root = doc.RootElement;

            if (root.TryGetProperty("default_scan_root", out var scanRoot))
                DefaultScanRoot = scanRoot.GetString();

            // Derive index directory the same way Python's ConfigManager does:
            // portable → <config_dir>/indexes/
            // standard → %LOCALAPPDATA%\SHL\DualPaneFileManager\indexes\
            string configDir = Path.GetDirectoryName(configPath) ?? AppContext.BaseDirectory;
            IndexDirectory = Path.Combine(configDir, "indexes");

            return true;
        }
        catch (JsonException)
        {
            return false;
        }
    }

    public static string ResolveConfigPath()
    {
        // Portable mode: config.json lives next to DFE.Indexer.exe
        string portablePath = Path.Combine(AppContext.BaseDirectory, ConfigFileName);
        if (File.Exists(portablePath))
            return portablePath;

        // Standard mode: %LOCALAPPDATA%\SHL\DualPaneFileManager\config.json
        string localApp = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        return Path.Combine(localApp, OrgPath, ConfigFileName);
    }

    public static string ResolveDbPath(string dbFileName)
    {
        if (IndexDirectory is not null)
            return Path.Combine(IndexDirectory, dbFileName);

        // Fallback: indexes/ next to the exe
        return Path.Combine(AppContext.BaseDirectory, "indexes", dbFileName);
    }
}
