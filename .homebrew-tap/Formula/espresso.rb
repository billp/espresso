class Espresso < Formula
  desc "macOS mouse mover that prevents screen sleep, managed via an interactive TUI"
  homepage "https://github.com/billp/espresso"
  url "https://raw.githubusercontent.com/billp/espresso/refs/heads/main/install.sh"
  version "0.0.15"
  license "MIT"

  depends_on :macos
  depends_on "python@3"

  def install
    # install.sh bundles the full Python script — extract and install it
    system "bash", cached_download, "--prefix=#{prefix}"
    bin.install "#{ENV["HOME"]}/.local/bin/espresso"
  end

  test do
    assert_match "espresso", shell_output("#{bin}/espresso --version 2>&1", 1)
  end
end
