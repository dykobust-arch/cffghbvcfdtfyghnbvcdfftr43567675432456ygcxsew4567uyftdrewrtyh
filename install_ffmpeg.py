import urllib.request
import zipfile
import os
import stat
from pathlib import Path

print("⏳ Скачиваю ffmpeg...")

url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz"
archive = Path("ffmpeg.tar.xz")

urllib.request.urlretrieve(url, archive)
print("✅ Скачал, распаковываю...")

os.system("tar -xf ffmpeg.tar.xz")

# Находим бинарник и копируем в текущую папку
for path in Path(".").rglob("ffmpeg"):
    if path.is_file():
        dest = Path("ffmpeg")
        dest.write_bytes(path.read_bytes())
        dest.chmod(dest.stat().st_mode | stat.S_IEXEC)
        print(f"✅ ffmpeg скопирован из {path}")
        break

# Чистим
archive.unlink(missing_ok=True)
os.system("rm -rf ffmpeg-master-latest-linux64-gpl")
print("✅ Готово! Проверяю...")
os.system("./ffmpeg -version")