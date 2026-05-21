#!/bin/bash
# 检查所有密钥文件非空
for f in /home/yang/projects/secrets/*.key; do
    if [ ! -s "$f" ]; then
        echo "ERROR: $f 是空文件，请填写密钥"
        exit 1
    fi
done
echo "All secrets files are non-empty"
