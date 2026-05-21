class Espresso < Formula
  desc "macOS mouse mover that prevents screen sleep, managed via an interactive TUI"
  homepage "https://github.com/billp/espresso"
  url "https://github.com/billp/espresso/archive/refs/tags/v0.0.16.tar.gz"
  sha256 "1dcf1a1206bb000fc6a743da7968d9abff7cdc54c3c26ac8b2b6f0af4720b204"
  version "0.0.16"
  license "MIT"

  depends_on :macos
  depends_on "python@3"

  def install
    system "env", "INSTALL_DIR=#{bin}", "bash", "install.sh"
  end

  test do
    assert_match "espresso", shell_output("#{bin}/espresso --version 2>&1", 1)
  end
end
