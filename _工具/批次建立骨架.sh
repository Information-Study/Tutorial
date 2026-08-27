#!/usr/bin/env bash
# stub.sh <資料夾> <tags> <category>  — 從 stdin 讀 「檔名|標題|desc|難度|目標(;)|延伸(,)」
set -euo pipefail
DIR="$1"; TAGS="$2"; CAT="$3"
mkdir -p "$DIR"
while IFS='|' read -r fn title desc diff goals related; do
  case "$fn" in ''|'#'*) continue;; esac
  {
    echo '---'
    echo "title: \"$title\""
    echo "desc: \"$desc\""
    echo "aliases: []"
    echo "tags: [$TAGS]"
    echo "category: $CAT"
    echo "difficulty: $diff"
    echo "status: 待撰寫"
    echo "distro: [ubuntu, rhel]"
    echo "prerequisites: []"
    echo "updated: 2026-08-27"
    echo '---'
    echo
    echo "# $title"
    echo
    echo "> [!abstract] 這篇你會學到"
    echo "$goals" | awk -F';' '{for(i=1;i<=NF;i++){gsub(/^ +| +$/,"",$i); if($i!="") print "> - " $i}}'
    echo
    echo "## 前置知識"
    echo
    echo "<!-- TODO: 待撰寫 -->"
    echo
    echo "## 觀念說明"
    echo
    echo "<!-- TODO: 待撰寫 -->"
    echo
    echo "## 環境準備與安裝"
    echo
    echo "<!-- TODO: 待撰寫 -->"
    echo
    echo "> [!info]- 平台差異對照"
    echo "> <!-- TODO: 待撰寫 -->"
    echo
    echo "## 基礎設定"
    echo
    echo "<!-- TODO: 待撰寫 -->"
    echo
    echo "## 進階設定與調校"
    echo
    echo "<!-- TODO: 待撰寫 -->"
    echo
    echo "## 完整實戰範例"
    echo
    echo "<!-- TODO: 待撰寫 -->"
    echo
    echo "## 常見錯誤與排錯"
    echo
    echo "| 現象 | 原因 | 解法 |"
    echo "| --- | --- | --- |"
    echo "|  |  |  |"
    echo
    echo "## 安全性注意事項"
    echo
    echo "> [!warning] 注意"
    echo "> <!-- TODO: 待撰寫 -->"
    echo
    echo "## 速查表"
    echo
    echo "| 指令 / 設定項 | 說明 | 範例 |"
    echo "| --- | --- | --- |"
    echo "|  |  |  |"
    echo
    echo "## 練習題"
    echo
    echo "> [!question]- 練習 1"
    echo "> <!-- TODO: 待撰寫 -->"
    echo
    echo "## 小測驗"
    echo
    echo "<!-- 最多 10 題，針對關鍵細節與易錯觀念 -->"
    echo
    echo "Q1. "
    echo "Q2. "
    echo "Q3. "
    echo
    echo "> [!question]- 測驗答案"
    echo "> **Q1.** "
    echo "> **Q2.** "
    echo "> **Q3.** "
    echo
    echo "## 延伸閱讀"
    echo
    echo "$related" | awk -F',' '{for(i=1;i<=NF;i++){gsub(/^ +| +$/,"",$i); if($i!="") print "- [[" $i "]]"}}'
  } > "$DIR/$fn"
done
