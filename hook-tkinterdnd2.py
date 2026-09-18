# PyInstaller 打包钩子：把 tkinterdnd2 的原生拖放组件一并放入 EXE。
from PyInstaller.utils.hooks import collect_data_files


datas = collect_data_files("tkinterdnd2")
