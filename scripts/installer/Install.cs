// Small per-user installer. The complete STEVE payload sits next to this executable.
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Security.Cryptography;
using System.Threading.Tasks;
using System.Windows.Forms;
using System.Collections.Generic;
using System.Web.Script.Serialization;
using System.Text.RegularExpressions;

class Installer : Form
{
    readonly Label status = new Label();
    readonly Button install = new Button();
    bool installing;
    bool installed;

    Installer()
    {
        Text = "Install STEVE";
        ClientSize = new Size(500, 310);
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        StartPosition = FormStartPosition.CenterScreen;
        BackColor = Color.FromArgb(21, 26, 29);
        ForeColor = Color.FromArgb(237, 236, 229);
        Font = new Font("Segoe UI", 10);
        var title = new Label { Text = "Meet STEVE.", Font = new Font("Segoe UI", 26), AutoSize = true, Location = new Point(28, 25) };
        var description = new Label { Text = "Your engineering partner inside Fusion.\nInstall STEVE, sign in with ChatGPT, and start a conversation.", AutoSize = true, Location = new Point(31, 94) };
        status.SetBounds(31, 155, 438, 68);
        status.Text = "Close Fusion before installing.\nInstalls for your Windows account. No administrator access needed.";
        status.ForeColor = Color.FromArgb(170, 188, 180);
        install.Text = "Install STEVE";
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
            status.Text = "Fusion is still running. Save your work and close Fusion,\nthen click Install STEVE again.";
            return;
        }
        installing = true;
        install.Enabled = false;
        status.Text = "Checking the package and installing STEVE…";
        try
        {
            string root = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                                       "Autodesk", "Autodesk Fusion 360", "API", "AddIns");
            await Task.Run(() => InstallPayload(AppDomain.CurrentDomain.BaseDirectory, root));
            status.Text = "Installed. Open Fusion, then choose STEVE in the Quick Access toolbar.\nIf needed, enable STEVE under Scripts and Add-ins first.";
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

    static void PlainDirectory(string path)
    {
        if (Directory.Exists(path) && (File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0)
            throw new IOException("Installation folders must not be filesystem links.");
    }

    static string PreviousInstallation(string root)
    {
        string found = null;
        foreach (string folder in Directory.GetDirectories(root))
        {
            string name = Path.GetFileName(folder);
            if (name.Equals("STEVE", StringComparison.OrdinalIgnoreCase) || !Regex.IsMatch(name, @"\A[A-Za-z][A-Za-z0-9_-]{0,79}\z")) continue;
            string marker = Path.Combine(folder, name.ToLowerInvariant() + "-install-marker.txt");
            string manifest = Path.Combine(folder, name + ".manifest");
            if (!File.Exists(marker) || !File.Exists(manifest) || !File.Exists(Path.Combine(folder, name + ".py"))) continue;
            if (File.ReadAllText(marker).Trim() != name + " managed installation") continue;
            Dictionary<string, object> metadata;
            try { metadata = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(File.ReadAllText(manifest)); }
            catch (ArgumentException) { continue; }
            object author, type, description, product;
            if (metadata == null || !metadata.TryGetValue("author", out author) || (string)author != "10-X-eng" ||
                !metadata.TryGetValue("type", out type) || (string)type != "addin" ||
                !metadata.TryGetValue("autodeskProduct", out product) || (string)product != "Fusion" ||
                !metadata.TryGetValue("description", out description)) continue;
            var descriptions = description as Dictionary<string, object>;
            object text;
            if (descriptions == null || !descriptions.TryGetValue("", out text) ||
                !(text is string) || !((string)text).Contains("Engineering & Visualization Expert")) continue;
            PlainDirectory(folder);
            if (found != null) throw new IOException("Multiple previous installations were found. Keep only the one you want to upgrade.");
            found = folder;
        }
        return found;
    }

    public static void InstallPayload(string package, string root)
    {
        string source = Path.Combine(package, "STEVE");
        string sums = Path.Combine(package, "SHA256SUMS");
        if (!File.Exists(sums) || !File.Exists(Path.Combine(source, "STEVE.manifest")))
            throw new InvalidDataException("Extract the entire STEVE zip before running the installer.");
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
                if (actual != line.Substring(0, 64)) throw new InvalidDataException("Package verification failed. Download STEVE again.");
            }
        }
        Directory.CreateDirectory(root);
        PlainDirectory(root);
        string previous = PreviousInstallation(root);
        string destination = Within(root, "STEVE");
        PlainDirectory(destination);
        string staging = Within(root, "STEVE-staging-" + Guid.NewGuid().ToString("N"));
        string backupRoot = Path.Combine(Directory.GetParent(root).FullName, "STEVE-install-backups");
        string backup = Path.Combine(backupRoot, DateTime.UtcNow.ToString("yyyyMMdd-HHmmss") + "-" + Guid.NewGuid().ToString("N"));
        if (Directory.Exists(destination) && !File.Exists(Path.Combine(destination, "steve-install-marker.txt")))
            throw new IOException("An unmanaged STEVE folder already exists. Rename it before installing.");
        if (previous != null && Directory.Exists(destination))
            throw new IOException("Both a previous installation and STEVE exist. Keep only the add-in you want to upgrade; saved data has not been changed.");
        Directory.CreateDirectory(staging);
        foreach (string line in lines)
        {
            string relative = line.Substring(66);
            string target = Within(staging, relative);
            Directory.CreateDirectory(Path.GetDirectoryName(target));
            File.Copy(Within(source, relative), target, true);
        }
        File.WriteAllText(Path.Combine(staging, "steve-install-marker.txt"), "STEVE managed installation");
        if (previous != null)
            File.WriteAllText(Path.Combine(staging, "steve-upgrade.json"), new JavaScriptSerializer().Serialize(
                new Dictionary<string, string> { { "previousName", Path.GetFileName(previous) } }));
        else if (File.Exists(Path.Combine(destination, "steve-upgrade.json")))
            File.Copy(Path.Combine(destination, "steve-upgrade.json"), Path.Combine(staging, "steve-upgrade.json"), true);
        string replaced = previous ?? destination;
        if (Directory.Exists(replaced))
        {
            Directory.CreateDirectory(backupRoot);
            PlainDirectory(backupRoot);
            Directory.Move(replaced, backup);
        }
        try { Directory.Move(staging, destination); }
        catch
        {
            if (Directory.Exists(backup) && !Directory.Exists(replaced)) Directory.Move(backup, replaced);
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
