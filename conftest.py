import sys
import pathlib

# 让测试可直接 import src.* 而无需安装包
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
