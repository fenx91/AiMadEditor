#!/bin/bash
# 使用虚拟环境中的 pytest 执行测试，防止调用系统全局 pytest 并忽略所有警告
./venv/bin/pytest -W ignore tests/
