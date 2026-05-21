class Espresso < Formula
  desc "macOS mouse mover that prevents screen sleep, managed via an interactive TUI"
  homepage "https://github.com/billp/espresso"
  url "https://raw.githubusercontent.com/billp/espresso/refs/heads/main/install.sh"
  version "0.0.15"
  license "MIT"

  depends_on :macos
  depends_on "python@3"

  def install
    system "env", "INSTALL_DIR=#{bin}", "bash", cached_download
  end

  test do
    assert_match "espresso", shell_output("#{bin}/espresso --version 2>&1", 1)
  end
end
