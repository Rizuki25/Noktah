using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Principal;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Win32;

[assembly: AssemblyTitle("Noktah Setup")]
[assembly: AssemblyDescription("Installer mandiri Noktah (tanpa folder Temp)")]
[assembly: AssemblyCompany("Rizuki25")]
[assembly: AssemblyProduct("Noktah")]
[assembly: AssemblyCopyright("Copyright (c) 2026 Rizuki25")]
[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]

namespace NoktahSetup
{
    internal static class IntegrityHelper
    {
        private const uint TOKEN_QUERY = 0x0008;
        private const int TokenIntegrityLevel = 25;
        private const int SECURITY_MANDATORY_MEDIUM_RID = 0x00002000;

        [StructLayout(LayoutKind.Sequential)]
        private struct SID_AND_ATTRIBUTES
        {
            public IntPtr Sid;
            public uint Attributes;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct TOKEN_MANDATORY_LABEL
        {
            public SID_AND_ATTRIBUTES Label;
        }

        [DllImport("advapi32.dll", SetLastError = true)]
        private static extern bool OpenProcessToken(IntPtr ProcessHandle, uint DesiredAccess, out IntPtr TokenHandle);

        [DllImport("advapi32.dll", SetLastError = true)]
        private static extern bool GetTokenInformation(
            IntPtr TokenHandle,
            int TokenInformationClass,
            IntPtr TokenInformation,
            uint TokenInformationLength,
            out uint ReturnLength);

        [DllImport("advapi32.dll", SetLastError = true)]
        private static extern IntPtr GetSidSubAuthorityCount(IntPtr pSid);

        [DllImport("advapi32.dll", SetLastError = true)]
        private static extern IntPtr GetSidSubAuthority(IntPtr pSid, uint nSubAuthority);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool CloseHandle(IntPtr hObject);

        public static bool IsLowIntegrityProcess()
        {
            IntPtr hToken = IntPtr.Zero;
            IntPtr pBuffer = IntPtr.Zero;
            try
            {
                if (!OpenProcessToken(Process.GetCurrentProcess().Handle, TOKEN_QUERY, out hToken))
                    return false;

                uint length = 0;
                GetTokenInformation(hToken, TokenIntegrityLevel, IntPtr.Zero, 0, out length);
                if (length == 0) return false;

                pBuffer = Marshal.AllocHGlobal((int)length);
                if (!GetTokenInformation(hToken, TokenIntegrityLevel, pBuffer, length, out length))
                    return false;

                TOKEN_MANDATORY_LABEL label = (TOKEN_MANDATORY_LABEL)Marshal.PtrToStructure(pBuffer, typeof(TOKEN_MANDATORY_LABEL));
                IntPtr pCount = GetSidSubAuthorityCount(label.Label.Sid);
                if (pCount == IntPtr.Zero) return false;

                byte count = Marshal.ReadByte(pCount);
                IntPtr pRid = GetSidSubAuthority(label.Label.Sid, (uint)(count - 1));
                if (pRid == IntPtr.Zero) return false;

                int rid = Marshal.ReadInt32(pRid);
                return rid < SECURITY_MANDATORY_MEDIUM_RID;
            }
            catch
            {
                return false;
            }
            finally
            {
                if (pBuffer != IntPtr.Zero) Marshal.FreeHGlobal(pBuffer);
                if (hToken != IntPtr.Zero) CloseHandle(hToken);
            }
        }

        public static bool IsAdministrator()
        {
            try
            {
                using (WindowsIdentity identity = WindowsIdentity.GetCurrent())
                {
                    WindowsPrincipal principal = new WindowsPrincipal(identity);
                    return principal.IsInRole(WindowsBuiltInRole.Administrator);
                }
            }
            catch
            {
                return false;
            }
        }

        public static void FixFileMediumIntegrity(string path)
        {
            try
            {
                if (string.IsNullOrWhiteSpace(path) || (!File.Exists(path) && !Directory.Exists(path)))
                    return;
                ProcessStartInfo psi = new ProcessStartInfo
                {
                    FileName = "icacls.exe",
                    Arguments = "\"" + path + "\" /setintegritylevel Medium",
                    WindowStyle = ProcessWindowStyle.Hidden,
                    CreateNoWindow = true,
                    UseShellExecute = false
                };
                using (Process p = Process.Start(psi))
                {
                    if (p != null) p.WaitForExit(3000);
                }
            }
            catch
            {
            }
        }

        public static bool RelaunchElevated(string extraArgs)
        {
            try
            {
                ProcessStartInfo psi = new ProcessStartInfo
                {
                    FileName = Application.ExecutablePath,
                    Arguments = extraArgs,
                    UseShellExecute = true,
                    Verb = "runas",
                    WorkingDirectory = Path.GetDirectoryName(Application.ExecutablePath) ?? Environment.CurrentDirectory
                };
                Process.Start(psi);
                return true;
            }
            catch
            {
                return false;
            }
        }
    }

    internal static class Program
    {
        public const string AppName = "Noktah";
        public const string AppVersion = "1.0.0";
        public const string AppPublisher = "Rizuki25";
        public const string AppUrl = "https://github.com/Rizuki25/Noktah";
        public const string AppExeName = "Noktah.exe";
        public const string UninstallExeName = "Uninstall-Noktah.exe";
        public const string UninstallRegKey = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\Noktah";

        [STAThread]
        private static int Main(string[] args)
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            bool isUninstall = false;
            bool isSilent = false;
            bool noElevate = false;
            bool autoInstall = false;
            bool optDesktop = true;
            bool optStartMenu = true;
            bool optStartup = true;
            bool optRunNow = true;
            string customDir = null;

            string currentExe = Path.GetFileName(Application.ExecutablePath) ?? "";
            if (currentExe.IndexOf("uninstall", StringComparison.OrdinalIgnoreCase) >= 0)
            {
                isUninstall = true;
            }

            foreach (string rawArg in args)
            {
                if (string.IsNullOrWhiteSpace(rawArg)) continue;
                string arg = rawArg.Trim();
                if (arg.Equals("/UNINSTALL", StringComparison.OrdinalIgnoreCase) ||
                    arg.Equals("--uninstall", StringComparison.OrdinalIgnoreCase) ||
                    arg.Equals("-u", StringComparison.OrdinalIgnoreCase))
                {
                    isUninstall = true;
                }
                else if (arg.Equals("/S", StringComparison.OrdinalIgnoreCase) ||
                         arg.Equals("/SILENT", StringComparison.OrdinalIgnoreCase) ||
                         arg.Equals("/VERYSILENT", StringComparison.OrdinalIgnoreCase) ||
                         arg.Equals("--silent", StringComparison.OrdinalIgnoreCase))
                {
                    isSilent = true;
                }
                else if (arg.Equals("/NOELEVATE", StringComparison.OrdinalIgnoreCase))
                {
                    noElevate = true;
                }
                else if (arg.Equals("/AUTOINSTALL", StringComparison.OrdinalIgnoreCase))
                {
                    autoInstall = true;
                }
                else if (arg.StartsWith("/DESKTOP=", StringComparison.OrdinalIgnoreCase))
                {
                    optDesktop = arg.Substring(9) == "1";
                }
                else if (arg.StartsWith("/STARTMENU=", StringComparison.OrdinalIgnoreCase))
                {
                    optStartMenu = arg.Substring(11) == "1";
                }
                else if (arg.StartsWith("/STARTUP=", StringComparison.OrdinalIgnoreCase))
                {
                    optStartup = arg.Substring(9) == "1";
                }
                else if (arg.StartsWith("/RUNNOW=", StringComparison.OrdinalIgnoreCase))
                {
                    optRunNow = arg.Substring(8) == "1";
                }
                else if (arg.StartsWith("/DIR=", StringComparison.OrdinalIgnoreCase))
                {
                    customDir = arg.Substring(5).Trim('"');
                }
                else if (arg.StartsWith("/D=", StringComparison.OrdinalIgnoreCase))
                {
                    customDir = arg.Substring(3).Trim('"');
                }
            }

            // Jika sudah berjalan dengan hak normal/admin setelah elevasi, perbaiki label Mandatory Integrity
            // pada file installer ini sendiri supaya klik-dua-kali berikutnya tidak lagi masuk Low Integrity.
            if (!IntegrityHelper.IsLowIntegrityProcess())
            {
                IntegrityHelper.FixFileMediumIntegrity(Application.ExecutablePath);
            }
            else if (!isSilent && !noElevate)
            {
                // Jika file .exe ini diwarisi label "Low Mandatory Level" dari folder sandbox,
                // Windows menjalankannya di Low Integrity sehingga semua penulisan ke C:\ atau D:\ ditolak (Access is denied).
                // Naikkan otomatis via UAC (runas) agar keluar dari Low Integrity.
                string passArgs = "/NOELEVATE";
                if (isUninstall) passArgs += " /UNINSTALL";
                if (!string.IsNullOrWhiteSpace(customDir)) passArgs += " \"/DIR=" + customDir + "\"";
                if (IntegrityHelper.RelaunchElevated(passArgs))
                {
                    return 0;
                }
            }

            if (isUninstall)
            {
                return RunUninstall(isSilent);
            }

            string targetDir = !string.IsNullOrWhiteSpace(customDir) ? customDir : GetDefaultInstallDir();

            if (isSilent)
            {
                try
                {
                    InstallEngine.RunInstall(
                        targetDir,
                        createDesktopShortcut: optDesktop,
                        createStartMenuShortcut: optStartMenu,
                        enableAutostart: false,
                        onProgress: null
                    );
                    return 0;
                }
                catch (Exception ex)
                {
                    Console.Error.WriteLine("Instalasi gagal: " + ex.Message);
                    return 1;
                }
            }

            using (SetupForm form = new SetupForm(targetDir, autoInstall, optDesktop, optStartMenu, optStartup, optRunNow))
            {
                Application.Run(form);
                return form.InstallSucceeded ? 0 : 1;
            }
        }

        public static string GetDefaultInstallDir()
        {
            string localAppData = Environment.GetEnvironmentVariable("LOCALAPPDATA");
            if (string.IsNullOrWhiteSpace(localAppData) || !Directory.Exists(localAppData))
            {
                string userProfile = Environment.GetEnvironmentVariable("USERPROFILE");
                if (!string.IsNullOrWhiteSpace(userProfile) && Directory.Exists(Path.Combine(userProfile, "AppData", "Local")))
                {
                    localAppData = Path.Combine(userProfile, "AppData", "Local");
                }
                else
                {
                    localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
                }
            }
            return Path.Combine(localAppData, "Programs", AppName);
        }

        public static int RunUninstall(bool silent)
        {
            string installDir = Path.GetDirectoryName(Application.ExecutablePath);
            try
            {
                using (RegistryKey key = Registry.CurrentUser.OpenSubKey(UninstallRegKey, false))
                {
                    if (key != null)
                    {
                        string regLoc = key.GetValue("InstallLocation") as string;
                        if (!string.IsNullOrWhiteSpace(regLoc) && Directory.Exists(regLoc))
                        {
                            installDir = regLoc;
                        }
                    }
                }
            }
            catch
            {
            }

            if (string.IsNullOrWhiteSpace(installDir) || !File.Exists(Path.Combine(installDir, AppExeName)))
            {
                string defaultDir = GetDefaultInstallDir();
                if (Directory.Exists(defaultDir))
                {
                    installDir = defaultDir;
                }
            }

            if (!silent)
            {
                DialogResult confirm = MessageBox.Show(
                    "Apakah Anda yakin ingin menghapus Noktah dari komputer Anda?",
                    "Uninstall Noktah",
                    MessageBoxButtons.YesNo,
                    MessageBoxIcon.Question
                );
                if (confirm != DialogResult.Yes)
                {
                    return 0;
                }
            }

            try
            {
                InstallEngine.StopRunningApp();
                InstallEngine.RemoveShortcuts();
                InstallEngine.RemoveUninstallRegistry();

                if (!string.IsNullOrWhiteSpace(installDir) && Directory.Exists(installDir))
                {
                    string selfPath = Path.GetFullPath(Application.ExecutablePath);
                    foreach (string file in Directory.GetFiles(installDir, "*", SearchOption.AllDirectories))
                    {
                        if (string.Equals(Path.GetFullPath(file), selfPath, StringComparison.OrdinalIgnoreCase))
                            continue;
                        try
                        {
                            File.SetAttributes(file, FileAttributes.Normal);
                            File.Delete(file);
                        }
                        catch
                        {
                        }
                    }

                    ProcessStartInfo psi = new ProcessStartInfo
                    {
                        FileName = "cmd.exe",
                        Arguments = "/c ping 127.0.0.1 -n 2 >nul & rmdir /s /q \"" + installDir + "\"",
                        WindowStyle = ProcessWindowStyle.Hidden,
                        CreateNoWindow = true,
                        UseShellExecute = false
                    };
                    Process.Start(psi);
                }

                if (!silent)
                {
                    MessageBox.Show(
                        "Noktah berhasil dihapus dari komputer Anda.",
                        "Uninstall Noktah",
                        MessageBoxButtons.OK,
                        MessageBoxIcon.Information
                    );
                }
                return 0;
            }
            catch (Exception ex)
            {
                if (!silent)
                {
                    MessageBox.Show(
                        "Gagal menghapus Noktah:\n" + ex.Message,
                        "Uninstall Noktah",
                        MessageBoxButtons.OK,
                        MessageBoxIcon.Error
                    );
                }
                return 1;
            }
        }
    }

    internal static class InstallEngine
    {
        public static void StopRunningApp()
        {
            try
            {
                Process[] procs = Process.GetProcessesByName("Noktah");
                foreach (Process p in procs)
                {
                    try
                    {
                        if (p.Id == Process.GetCurrentProcess().Id) continue;
                        p.Kill();
                        p.WaitForExit(3000);
                    }
                    catch
                    {
                    }
                }
            }
            catch
            {
            }
        }

        public static void RunInstall(
            string targetDir,
            bool createDesktopShortcut,
            bool createStartMenuShortcut,
            bool enableAutostart,
            Action<int, string> onProgress)
        {
            if (onProgress != null) onProgress(2, "Menghentikan proses Noktah yang sedang berjalan...");
            StopRunningApp();

            if (onProgress != null) onProgress(5, "Menyiapkan folder tujuan...");
            Directory.CreateDirectory(targetDir);

            // Pastikan probe tulis berhasil di folder tujuan sebelum mengekstrak 800+ file
            string probeFile = Path.Combine(targetDir, ".noktah_write_check");
            using (FileStream fs = new FileStream(probeFile, FileMode.Create, FileAccess.Write, FileShare.None))
            {
                fs.WriteByte(1);
            }
            File.Delete(probeFile);

            Assembly asm = Assembly.GetExecutingAssembly();
            using (Stream zipStream = asm.GetManifestResourceStream("Noktah.Payload.zip"))
            {
                if (zipStream == null)
                {
                    throw new InvalidOperationException("Resource paket instalasi (Noktah.Payload.zip) tidak ditemukan di dalam installer.");
                }

                using (ZipArchive archive = new ZipArchive(zipStream, ZipArchiveMode.Read))
                {
                    int total = archive.Entries.Count;
                    int index = 0;

                    foreach (ZipArchiveEntry entry in archive.Entries)
                    {
                        index++;
                        string relPath = entry.FullName.Replace('/', Path.DirectorySeparatorChar).Replace('\\', Path.DirectorySeparatorChar);
                        string destPath = Path.Combine(targetDir, relPath);

                        if (string.IsNullOrEmpty(entry.Name))
                        {
                            Directory.CreateDirectory(destPath);
                            continue;
                        }

                        string parentDir = Path.GetDirectoryName(destPath);
                        if (!string.IsNullOrEmpty(parentDir))
                        {
                            Directory.CreateDirectory(parentDir);
                        }

                        int pct = 5 + (int)((index * 80.0) / Math.Max(1, total));
                        if (onProgress != null && (index % 3 == 0 || index == total))
                        {
                            onProgress(pct, "Mengekstrak: " + entry.Name);
                        }

                        WriteEntryWithRetry(entry, destPath);
                    }
                }
            }

            string appExePath = Path.Combine(targetDir, Program.AppExeName);
            string uninstallExePath = Path.Combine(targetDir, Program.UninstallExeName);
            IntegrityHelper.FixFileMediumIntegrity(targetDir);
            IntegrityHelper.FixFileMediumIntegrity(appExePath);
            IntegrityHelper.FixFileMediumIntegrity(uninstallExePath);

            if (onProgress != null) onProgress(90, "Membuat shortcut aplikasi...");

            if (createStartMenuShortcut)
            {
                string startMenuDir = Environment.GetFolderPath(Environment.SpecialFolder.Programs);
                if (!string.IsNullOrEmpty(startMenuDir))
                {
                    CreateShortcut(
                        Path.Combine(startMenuDir, "Noktah.lnk"),
                        appExePath,
                        targetDir,
                        "Noktah - Notch pemutar musik untuk Windows"
                    );
                }
            }

            if (createDesktopShortcut)
            {
                string desktopDir = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
                if (!string.IsNullOrEmpty(desktopDir))
                {
                    CreateShortcut(
                        Path.Combine(desktopDir, "Noktah.lnk"),
                        appExePath,
                        targetDir,
                        "Noktah - Notch pemutar musik untuk Windows"
                    );
                }
            }

            string startupDir = Environment.GetFolderPath(Environment.SpecialFolder.Startup);
            if (!string.IsNullOrEmpty(startupDir))
            {
                string startupLnk = Path.Combine(startupDir, "Noktah.lnk");
                if (enableAutostart)
                {
                    CreateShortcut(
                        startupLnk,
                        appExePath,
                        targetDir,
                        "Noktah - Notch pemutar musik untuk Windows"
                    );
                }
                else if (File.Exists(startupLnk))
                {
                    try { File.Delete(startupLnk); } catch { }
                }
            }

            if (onProgress != null) onProgress(96, "Mendaftarkan aplikasi di Windows...");
            RegisterUninstall(targetDir, appExePath, uninstallExePath);

            if (onProgress != null) onProgress(100, "Pemasangan selesai!");
        }

        private static void WriteEntryWithRetry(ZipArchiveEntry entry, string destPath)
        {
            Exception lastError = null;
            for (int attempt = 0; attempt < 5; attempt++)
            {
                try
                {
                    if (File.Exists(destPath))
                    {
                        File.SetAttributes(destPath, FileAttributes.Normal);
                    }
                    using (Stream inStream = entry.Open())
                    using (FileStream outStream = new FileStream(destPath, FileMode.Create, FileAccess.Write, FileShare.None))
                    {
                        inStream.CopyTo(outStream);
                    }
                    return;
                }
                catch (UnauthorizedAccessException)
                {
                    throw;
                }
                catch (Exception ex)
                {
                    lastError = ex;
                    Thread.Sleep(250);
                }
            }
            if (lastError is UnauthorizedAccessException)
                throw lastError;
            throw new IOException("Gagal menulis file '" + destPath + "': " + (lastError != null ? lastError.Message : "Access denied"), lastError);
        }

        public static void CreateShortcut(string lnkPath, string targetExe, string workingDir, string description)
        {
            try
            {
                Type shellType = Type.GetTypeFromProgID("WScript.Shell");
                if (shellType == null) return;
                object shell = Activator.CreateInstance(shellType);
                object shortcut = shellType.InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, null, shell, new object[] { lnkPath });
                if (shortcut == null) return;

                Type scType = shortcut.GetType();
                scType.InvokeMember("TargetPath", BindingFlags.SetProperty, null, shortcut, new object[] { targetExe });
                scType.InvokeMember("WorkingDirectory", BindingFlags.SetProperty, null, shortcut, new object[] { workingDir });
                scType.InvokeMember("IconLocation", BindingFlags.SetProperty, null, shortcut, new object[] { targetExe + ",0" });
                scType.InvokeMember("Description", BindingFlags.SetProperty, null, shortcut, new object[] { description });
                scType.InvokeMember("Save", BindingFlags.InvokeMethod, null, shortcut, null);
            }
            catch
            {
            }
        }

        public static void RemoveShortcuts()
        {
            string[] paths = new string[]
            {
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), "Noktah.lnk"),
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs), "Noktah.lnk"),
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Startup), "Noktah.lnk")
            };
            foreach (string p in paths)
            {
                try
                {
                    if (File.Exists(p)) File.Delete(p);
                }
                catch
                {
                }
            }
        }

        private static void RegisterUninstall(string targetDir, string appExePath, string uninstallExePath)
        {
            try
            {
                using (RegistryKey key = Registry.CurrentUser.CreateSubKey(Program.UninstallRegKey))
                {
                    if (key == null) return;
                    key.SetValue("DisplayName", Program.AppName);
                    key.SetValue("DisplayVersion", Program.AppVersion);
                    key.SetValue("Publisher", Program.AppPublisher);
                    key.SetValue("URLInfoAbout", Program.AppUrl);
                    key.SetValue("DisplayIcon", appExePath);
                    key.SetValue("InstallLocation", targetDir);
                    key.SetValue("UninstallString", "\"" + uninstallExePath + "\" /UNINSTALL");
                    key.SetValue("QuietUninstallString", "\"" + uninstallExePath + "\" /UNINSTALL /SILENT");
                    key.SetValue("NoModify", 1, RegistryValueKind.DWord);
                    key.SetValue("NoRepair", 1, RegistryValueKind.DWord);
                }
            }
            catch
            {
            }
        }

        public static void RemoveUninstallRegistry()
        {
            try
            {
                Registry.CurrentUser.DeleteSubKeyTree(Program.UninstallRegKey, false);
            }
            catch
            {
            }
        }
    }

    internal sealed class SetupForm : Form
    {
        private readonly TextBox _dirBox;
        private readonly Button _browseBtn;
        private readonly CheckBox _chkDesktop;
        private readonly CheckBox _chkStartMenu;
        private readonly CheckBox _chkStartup;
        private readonly CheckBox _chkRunNow;
        private readonly ProgressBar _progressBar;
        private readonly Label _statusLabel;
        private readonly Button _installBtn;
        private readonly Button _cancelBtn;

        private readonly bool _autoInstallOnLoad;
        private bool _installing;
        public bool InstallSucceeded { get; private set; }

        public SetupForm(
            string initialDir,
            bool autoInstall = false,
            bool optDesktop = true,
            bool optStartMenu = true,
            bool optStartup = true,
            bool optRunNow = true)
        {
            _autoInstallOnLoad = autoInstall;

            Text = "Setup - Noktah " + Program.AppVersion;
            ClientSize = new Size(520, 410);
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            StartPosition = FormStartPosition.CenterScreen;
            BackColor = Color.FromArgb(18, 19, 24);
            ForeColor = Color.FromArgb(235, 237, 245);
            Font = new Font("Segoe UI", 9.5f, FontStyle.Regular);

            try
            {
                Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
            }
            catch
            {
            }

            // Header Panel
            Panel header = new Panel
            {
                Dock = DockStyle.Top,
                Height = 86,
                BackColor = Color.FromArgb(26, 28, 36)
            };
            Controls.Add(header);

            PictureBox logoBox = new PictureBox
            {
                Bounds = new Rectangle(24, 17, 52, 52),
                SizeMode = PictureBoxSizeMode.Zoom,
                BackColor = Color.Transparent
            };
            try
            {
                using (Stream imgStream = Assembly.GetExecutingAssembly().GetManifestResourceStream("Noktah.Logo.png"))
                {
                    if (imgStream != null)
                    {
                        logoBox.Image = Image.FromStream(imgStream);
                    }
                }
            }
            catch
            {
            }
            header.Controls.Add(logoBox);

            Label titleLabel = new Label
            {
                Text = "Pasang Noktah v" + Program.AppVersion,
                Font = new Font("Segoe UI Semibold", 15f, FontStyle.Bold),
                ForeColor = Color.White,
                AutoSize = true,
                Location = new Point(90, 18)
            };
            header.Controls.Add(titleLabel);

            Label subTitleLabel = new Label
            {
                Text = "Notch pemutar musik untuk Windows",
                Font = new Font("Segoe UI", 9.2f, FontStyle.Regular),
                ForeColor = Color.FromArgb(170, 176, 195),
                AutoSize = true,
                Location = new Point(92, 48)
            };
            header.Controls.Add(subTitleLabel);

            // Folder Tujuan
            Label dirLabel = new Label
            {
                Text = "Folder pemasangan:",
                AutoSize = true,
                ForeColor = Color.FromArgb(200, 205, 220),
                Location = new Point(24, 104)
            };
            Controls.Add(dirLabel);

            _dirBox = new TextBox
            {
                Text = initialDir,
                Bounds = new Rectangle(24, 128, 382, 27),
                BackColor = Color.FromArgb(30, 32, 42),
                ForeColor = Color.White,
                BorderStyle = BorderStyle.FixedSingle
            };
            Controls.Add(_dirBox);

            _browseBtn = new Button
            {
                Text = "Pilih...",
                Bounds = new Rectangle(414, 126, 82, 29),
                FlatStyle = FlatStyle.Flat,
                BackColor = Color.FromArgb(40, 44, 58),
                ForeColor = Color.White,
                Cursor = Cursors.Hand
            };
            _browseBtn.FlatAppearance.BorderColor = Color.FromArgb(68, 74, 96);
            _browseBtn.Click += OnBrowseClick;
            Controls.Add(_browseBtn);

            // Opsi
            Label optLabel = new Label
            {
                Text = "Opsi pemasangan:",
                AutoSize = true,
                ForeColor = Color.FromArgb(200, 205, 220),
                Location = new Point(24, 172)
            };
            Controls.Add(optLabel);

            _chkDesktop = new CheckBox
            {
                Text = "Buat shortcut di Desktop",
                Checked = optDesktop,
                AutoSize = true,
                Location = new Point(28, 198),
                ForeColor = Color.FromArgb(230, 233, 242)
            };
            Controls.Add(_chkDesktop);

            _chkStartMenu = new CheckBox
            {
                Text = "Buat shortcut di Start Menu",
                Checked = optStartMenu,
                AutoSize = true,
                Location = new Point(28, 226),
                ForeColor = Color.FromArgb(230, 233, 242)
            };
            Controls.Add(_chkStartMenu);

            _chkStartup = new CheckBox
            {
                Text = "Jalankan Noktah otomatis saat login Windows",
                Checked = optStartup,
                AutoSize = true,
                Location = new Point(28, 254),
                ForeColor = Color.FromArgb(230, 233, 242)
            };
            Controls.Add(_chkStartup);

            _chkRunNow = new CheckBox
            {
                Text = "Jalankan Noktah sekarang setelah pemasangan selesai",
                Checked = optRunNow,
                AutoSize = true,
                Location = new Point(28, 282),
                ForeColor = Color.FromArgb(230, 233, 242)
            };
            Controls.Add(_chkRunNow);

            // Progress & Status
            _statusLabel = new Label
            {
                Text = "Siap memasang Noktah.",
                AutoSize = false,
                Bounds = new Rectangle(24, 316, 472, 20),
                ForeColor = Color.FromArgb(165, 172, 192)
            };
            Controls.Add(_statusLabel);

            _progressBar = new ProgressBar
            {
                Bounds = new Rectangle(24, 338, 472, 14),
                Minimum = 0,
                Maximum = 100,
                Value = 0,
                Style = ProgressBarStyle.Continuous
            };
            Controls.Add(_progressBar);

            // Tombol Bawah
            _installBtn = new Button
            {
                Text = "Pasang Sekarang",
                Bounds = new Rectangle(266, 364, 136, 34),
                FlatStyle = FlatStyle.Flat,
                BackColor = Color.FromArgb(78, 115, 248),
                ForeColor = Color.White,
                Font = new Font("Segoe UI Semibold", 9.5f, FontStyle.Bold),
                Cursor = Cursors.Hand
            };
            _installBtn.FlatAppearance.BorderSize = 0;
            _installBtn.Click += OnInstallClick;
            Controls.Add(_installBtn);

            _cancelBtn = new Button
            {
                Text = "Batal",
                Bounds = new Rectangle(410, 364, 86, 34),
                FlatStyle = FlatStyle.Flat,
                BackColor = Color.FromArgb(40, 44, 58),
                ForeColor = Color.White,
                Cursor = Cursors.Hand
            };
            _cancelBtn.FlatAppearance.BorderColor = Color.FromArgb(68, 74, 96);
            _cancelBtn.Click += (s, e) => Close();
            Controls.Add(_cancelBtn);

            AcceptButton = _installBtn;
        }

        protected override void OnShown(EventArgs e)
        {
            base.OnShown(e);
            if (_autoInstallOnLoad)
            {
                OnInstallClick(this, EventArgs.Empty);
            }
        }

        private void OnBrowseClick(object sender, EventArgs e)
        {
            using (FolderBrowserDialog dlg = new FolderBrowserDialog())
            {
                dlg.Description = "Pilih folder tempat memasang Noktah:";
                dlg.SelectedPath = _dirBox.Text;
                if (dlg.ShowDialog(this) == DialogResult.OK && !string.IsNullOrWhiteSpace(dlg.SelectedPath))
                {
                    string chosen = dlg.SelectedPath;
                    if (!chosen.EndsWith(Program.AppName, StringComparison.OrdinalIgnoreCase))
                    {
                        chosen = Path.Combine(chosen, Program.AppName);
                    }
                    _dirBox.Text = chosen;
                }
            }
        }

        private void OnInstallClick(object sender, EventArgs e)
        {
            if (InstallSucceeded)
            {
                if (_chkRunNow.Checked)
                {
                    TryLaunchInstalledApp(_dirBox.Text.Trim());
                }
                Close();
                return;
            }

            if (_installing) return;

            string targetDir = _dirBox.Text.Trim();
            if (string.IsNullOrWhiteSpace(targetDir))
            {
                MessageBox.Show(this, "Silakan pilih folder tujuan pemasangan terlebih dahulu.", "Noktah Setup", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }

            _installing = true;
            _dirBox.Enabled = false;
            _browseBtn.Enabled = false;
            _chkDesktop.Enabled = false;
            _chkStartMenu.Enabled = false;
            _chkStartup.Enabled = false;
            _installBtn.Enabled = false;
            _cancelBtn.Enabled = false;

            bool makeDesktop = _chkDesktop.Checked;
            bool makeStartMenu = _chkStartMenu.Checked;
            bool makeStartup = _chkStartup.Checked;
            bool runNow = _chkRunNow.Checked;

            Thread worker = new Thread(() =>
            {
                try
                {
                    InstallEngine.RunInstall(
                        targetDir,
                        makeDesktop,
                        makeStartMenu,
                        makeStartup,
                        (pct, msg) =>
                        {
                            if (IsDisposed) return;
                            BeginInvoke((Action)(() =>
                            {
                                _progressBar.Value = Math.Max(0, Math.Min(100, pct));
                                _statusLabel.Text = msg;
                            }));
                        }
                    );

                    if (!IsDisposed)
                    {
                        BeginInvoke((Action)(() =>
                        {
                            _installing = false;
                            InstallSucceeded = true;
                            _progressBar.Value = 100;
                            _statusLabel.ForeColor = Color.FromArgb(110, 231, 183);
                            _statusLabel.Text = "Noktah berhasil dipasang di " + targetDir;
                            _installBtn.Text = "Selesai";
                            _installBtn.BackColor = Color.FromArgb(34, 160, 107);
                            _installBtn.Enabled = true;
                            _installBtn.Focus();
                        }));
                    }
                }
                catch (UnauthorizedAccessException uaEx)
                {
                    if (!IsDisposed)
                    {
                        BeginInvoke((Action)(() =>
                        {
                            _installing = false;
                            if (!IntegrityHelper.IsAdministrator())
                            {
                                string args = string.Format(
                                    "/NOELEVATE /AUTOINSTALL \"/DIR={0}\" /DESKTOP={1} /STARTMENU={2} /STARTUP={3} /RUNNOW={4}",
                                    targetDir,
                                    makeDesktop ? "1" : "0",
                                    makeStartMenu ? "1" : "0",
                                    makeStartup ? "1" : "0",
                                    runNow ? "1" : "0"
                                );
                                if (IntegrityHelper.RelaunchElevated(args))
                                {
                                    Close();
                                    return;
                                }
                            }

                            ReenableControls(uaEx.Message);
                        }));
                    }
                }
                catch (Exception ex)
                {
                    if (!IsDisposed)
                    {
                        BeginInvoke((Action)(() =>
                        {
                            _installing = false;
                            ReenableControls(ex.Message);
                        }));
                    }
                }
            });
            worker.IsBackground = true;
            worker.Start();
        }

        private void ReenableControls(string errMsg)
        {
            _dirBox.Enabled = true;
            _browseBtn.Enabled = true;
            _chkDesktop.Enabled = true;
            _chkStartMenu.Enabled = true;
            _chkStartup.Enabled = true;
            _installBtn.Enabled = true;
            _cancelBtn.Enabled = true;
            _statusLabel.ForeColor = Color.FromArgb(248, 113, 113);
            _statusLabel.Text = "Gagal: " + errMsg;

            MessageBox.Show(
                this,
                "Terjadi kesalahan saat memasang Noktah:\n\n" + errMsg,
                "Noktah Setup",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error
            );
        }

        private static void TryLaunchInstalledApp(string targetDir)
        {
            try
            {
                string exePath = Path.Combine(targetDir, Program.AppExeName);
                if (File.Exists(exePath))
                {
                    ProcessStartInfo psi = new ProcessStartInfo
                    {
                        FileName = exePath,
                        WorkingDirectory = targetDir,
                        UseShellExecute = true
                    };
                    Process.Start(psi);
                }
            }
            catch
            {
            }
        }

        protected override void OnFormClosing(FormClosingEventArgs e)
        {
            if (_installing)
            {
                e.Cancel = true;
                return;
            }
            base.OnFormClosing(e);
        }
    }
}
