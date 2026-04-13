using System;
using System.Diagnostics;
using System.Text;
using System.Text.Json;
using System.Threading;
using DFE.Indexer.Services;

namespace DFE.Indexer;

class Program
{
    static int Main(string[] args)
    {
        // Force UTF-8 stdout so Python readline() handles Chinese filenames correctly
        Console.OutputEncoding = Encoding.UTF8;

        string dbPath    = string.Empty;
        string rootPath  = string.Empty;
        int    notifyPort = 13377;
        bool   watchMode  = false;

        for (int i = 0; i < args.Length; i++)
        {
            switch (args[i])
            {
                case "--db"           when i + 1 < args.Length: dbPath      = args[++i]; break;
                case "--root"         when i + 1 < args.Length: rootPath    = args[++i]; break;
                case "--notify-port"  when i + 1 < args.Length: int.TryParse(args[++i], out notifyPort); break;
                case "--watch":       watchMode = true; break;
            }
        }

        // Fall back to config.json values if args not supplied
        ConfigReader.TryLoad();
        if (string.IsNullOrEmpty(dbPath))   dbPath   = ConfigReader.ResolveDbPath("master.db");
        if (string.IsNullOrEmpty(rootPath)) rootPath = ConfigReader.DefaultScanRoot ?? string.Empty;

        if (string.IsNullOrEmpty(rootPath))
        {
            WriteJson(new { error = "Missing --root argument and no default_scan_root in config.json." });
            return 1;
        }

        if (!System.IO.Directory.Exists(rootPath))
        {
            WriteJson(new { error = $"Root path does not exist: {rootPath}" });
            return 1;
        }

        // Ensure index directory exists
        string? indexDir = System.IO.Path.GetDirectoryName(dbPath);
        if (indexDir is not null && !System.IO.Directory.Exists(indexDir))
            System.IO.Directory.CreateDirectory(indexDir);

        // ── Phase 1: Initial bulk scan ────────────────────────────────────────
        var sw = Stopwatch.StartNew();
        int totalIndexed = 0;

        using var writer = new SqliteIndexWriter(dbPath);
        writer.InitializePragmas();

        try
        {
            writer.BeginTransaction();

            foreach (var record in DirectoryScanner.Scan(rootPath))
            {
                writer.UpsertFile(record);
                totalIndexed++;

                if (totalIndexed % 200 == 0)
                {
                    writer.CommitTransaction();
                    WriteJson(new { indexed = totalIndexed });
                    writer.BeginTransaction();
                }
            }

            writer.CommitTransaction();
            writer.UpdateScanMetadata(rootPath, watchMode ? "watching" : "done", totalIndexed);
        }
        catch (Exception ex)
        {
            WriteJson(new { error = ex.Message, trace = ex.StackTrace });
            return 2;
        }

        sw.Stop();
        WriteJson(new { status = watchMode ? "watching" : "done", total_files = totalIndexed, elapsed_ms = sw.ElapsedMilliseconds });

        if (!watchMode) return 0;

        // ── Phase 2: Real-time FileSystemWatcher ──────────────────────────────
        using var notifier = new UdpNotifier(notifyPort);
        using var watcher  = new FileWatcher(rootPath, writer, notifier);

        WriteJson(new { status = "watch_started", root = rootPath, notify_port = notifyPort });

        // Block until stdin is closed (Python calls process.stdin.close() / terminate())
        using var exit = new ManualResetEventSlim(false);
        Console.CancelKeyPress += (_, e) => { e.Cancel = true; exit.Set(); };

        // Also exit cleanly when the parent process closes stdin
        var stdinThread = new System.Threading.Thread(() =>
        {
            try { while (Console.In.Read() != -1) { } } catch { }
            exit.Set();
        }) { IsBackground = true };
        stdinThread.Start();

        exit.Wait();
        WriteJson(new { status = "watch_stopped" });
        return 0;
    }

    private static void WriteJson<T>(T obj)
    {
        Console.WriteLine(JsonSerializer.Serialize(obj));
        Console.Out.Flush();
    }
}
