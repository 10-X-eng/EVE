// Small per-user installer. The complete EVE payload sits next to this executable.
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Security.Cryptography;
using System.Threading.Tasks;
using System.Windows.Forms;

class Installer : Form
{
    readonly Label status = new Label();
    readonly Button install = new Button();
    bool installing;
    bool installed;

    Installer()
    {
        Text = "Install EVE";
        ClientSize = new Size(500, 310);
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;
        BackColor = Color.FromArgb(21, 26, 29);
        ForeColor = Color.FromArgb(237, 236, 229);
        Font = new Font("Segoe UI", 10);
        var title = new Label { Text = "Meet EVE.", Font = new Font("Segoe UI", 26), AutoSize = true, Location = new Point(28, 25) };
        var description = new Label { Text = "Your engineering partner inside Fusion.\nInstall EVE, sign in with ChatGPT, and start a conversation.", AutoSize = true, Location = new Point(31, 94) };
        status.SetBounds(31, 155, 438, 68);
        status.Text = "Close Fusion before installing.\nInstalls for your Windows account. No administrator access needed.";
        status.ForeColor = Color.FromArgb(170, 188, 180);
        install.Text = "Install EVE";
        install.SetBounds(31, 235, 438, 43);
        install.BackColor = Color.FromArgb(181, 223, 204);
        install.ForeColor = Color.FromArgb(27, 48, 39);
        install.FlatStyle = FlatStyle.Flat;
        install.Click += async (sender, e) => await Install();
        Controls.AddRange(new Control[] { title, description, status, install });
        FormClosing += (sender, e) => { if (installing) e.Cancel = true; };
    }

    async Task Install()
    {
        if (installed) { Close(); return; }
        if (Process.GetProcessesByName("Fusion360").Length != 0)
        {
            status.Text = "Fusion is still running. Save your work and close Fusion,\nthen click Install EVE again.";
            return;
        }
        installing = true;
        install.Enabled = false;
        status.Text = "Checking the package and installing EVE…";
        try
        {
            string root = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                                       "Autodesk", "Autodesk Fusion 360", "API", "AddIns");
            await Task.Run(() => InstallPayload(AppDomain.CurrentDomain.BaseDirectory, root));
            status.Text = "Installed. Open Fusion, then choose EVE in the Quick Access toolbar.\nIf needed, enable EVE under Scripts and Add-ins first.";
            install.Text = "Done";
            installed = true;
        }
        catch (Exception error)
        {
            status.Text = "Installation did not finish. " + error.Message;
        }
        finally
        {
            installing = false;
            install.Enabled = true;
        }
    }

    static string Within(string root, string relative)
    {
        string fullRoot = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        string target = Path.GetFullPath(Path.Combine(fullRoot, relative));
        if (Path.IsPathRooted(relative) || !target.StartsWith(fullRoot, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("The package contains an invalid path.");
        return target;
    }

    public static void InstallPayload(string package, string root)
    {
        string source = Path.Combine(package, "EVE");
        string sums = Path.Combine(package, "SHA256SUMS");
        if (!File.Exists(sums) || !File.Exists(Path.Combine(source, "EVE.manifest")))
            throw new InvalidDataException("Extract the entire EVE zip before running the installer.");
        string[] lines = File.ReadAllLines(sums);
        if (lines.Length == 0) throw new InvalidDataException("The package manifest is empty.");
        // Validate every listed file before changing the installation.
        foreach (string line in lines)
        {
            if (line.Length < 67 || line.Substring(64, 2) != "  ") throw new InvalidDataException("Invalid checksum manifest.");
            string path = Within(source, line.Substring(66));
            using (var stream = File.OpenRead(path))
            using (var hash = SHA256.Create())
            {
                string actual = BitConverter.ToString(hash.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
                if (actual != line.Substring(0, 64)) throw new InvalidDataException("Package verification failed. Download EVE again.");
            }
        }
        Directory.CreateDirectory(root);
        string destination = Within(root, "EVE");
        string staging = Within(root, "EVE-staging-" + Guid.NewGuid().ToString("N"));
        string backupRoot = Path.Combine(Directory.GetParent(root).FullName, "EVE-install-backups");
        string backup = Path.Combine(backupRoot, DateTime.UtcNow.ToString("yyyyMMdd-HHmmss") + "-" + Guid.NewGuid().ToString("N"));
        if (Directory.Exists(destination) && !File.Exists(Path.Combine(destination, "eve-install-marker.txt")))
            throw new IOException("An unmanaged EVE folder already exists. Rename it before installing.");
        Directory.CreateDirectory(staging);
        foreach (string line in lines)
        {
            string relative = line.Substring(66);
            string target = Within(staging, relative);
            Directory.CreateDirectory(Path.GetDirectoryName(target));
            File.Copy(Within(source, relative), target, true);
        }
        File.WriteAllText(Path.Combine(staging, "eve-install-marker.txt"), "EVE 0.1.0");
        if (Directory.Exists(destination))
        {
            Directory.CreateDirectory(backupRoot);
            Directory.Move(destination, backup);
        }
        try { Directory.Move(staging, destination); }
        catch
        {
            if (Directory.Exists(backup) && !Directory.Exists(destination)) Directory.Move(backup, destination);
            throw;
        }
    }

    [STAThread]
    static int Main(string[] args)
    {
        // Test mode requires an explicit destination and does not touch Fusion's installation.
        if (args.Length == 3 && args[0] == "--test-install")
        {
            try { InstallPayload(args[1], args[2]); return 0; }
            catch (Exception error) { File.WriteAllText(Path.Combine(args[1], "installer-test-error.txt"), error.ToString()); return 1; }
        }
        Application.EnableVisualStyles();
        Application.Run(new Installer());
        return 0;
    }
}
