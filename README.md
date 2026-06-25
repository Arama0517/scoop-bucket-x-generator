# scoop-bucket-x

适合中国大陆的 [scoop](https://scoop.sh) 代理镜像 bucket. 同步了几乎整个 `GitHub` 能找到的全部 bucket

## 使用方法

### 删除 `main` 仓库

```powershell
scoop bucket rm main
```

### 添加本仓库

> [!NOTE]
> 默认为 `bucket` 分支, 此分支没有替换下载链接为镜像
>
> 如果你安装的 [scoop](https://scoop.sh) 是 [scoop国内镜像优化库](https://gitee.com/scoop-installer/scoop) 也请使用镜像加速

(推荐) 使用镜像加速下载和更新的速度:

```powershell
scoop bucket add main https://v4.gh-proxy.org/https://github.com/Arama0517/scoop-bucket-x.git
```

(如果你无法使用上面的命令) 无镜像:

```powershell
scoop bucket add main https://github.com/Arama0517/scoop-bucket-x.git
```

### (可选) 更换分支

> [!NOTE]
> 以下命令为 `proxy_bucket` 分支, 会将部分下载链接替换为镜像
>
> 如果你想要改为没有镜像的版本, 请将 `git switch proxy_bucket` 替换为 `git switch bucket`

```powershell
$path = if ($env:SCOOP) { $env:SCOOP } else { "$env:USERPROFILE\scoop" }
cd $path\buckets\main
git fetch --all && git switch proxy_bucket
```

### (可选) 将已安装应用的上游替换为本仓库

```powershell
$path = if ($env:SCOOP) { $env:SCOOP } else { "$env:USERPROFILE\scoop" }

# 备份
scoop export > $path\source_backup.json

# 替换
Get-ChildItem $path\apps\*\current\install.json -Recurse |
  ForEach-Object {
    $j = Get-Content $_ -Raw | ConvertFrom-Json
    $j.bucket = "main"
    $j | ConvertTo-Json -Depth 10 | Set-Content $_
  }
scoop update && scoop update *
```

## 常见问题

### 运行 `scoop search` 过慢

由于本仓库同步了太多的应用, 官方的基于 `PowerShell` 编写的 `scoop search` 命令效率差到无法使用

推荐安装并使用基于 `zig` 语言开发的 `scoop-search` 工具替代

```powershell
scoop install scoop-search
# 搜索 Python
scoop-search python
```

### `Hash Check Failed`

由于部分应用配置的下载地址为最新发布地址, 但同时又配置了 hash 值, 当其有新版本变更时则会出现 `Hash Check Failed` 的问题. 此时可以添加参数 `-s` 以忽略. 示例:

```powershell
scoop install scoop-search -s
```

### `aria2` 下载失败

当安装了 `aria2` 时, `scoop` 会采用 `aria2` 实现分片加速下载. 但部分下载地址不支持或屏蔽了来自 `aria2` 的分片下载请求, 此时可以执行如下命令禁用 `aria2`：

```powershell
scoop config aria2-enabled false
```

### 撤回 [步骤4](#可选-将已安装应用的上游替换为本仓库)

```powershell
$path = if ($env:SCOOP) { $env:SCOOP } else { "$env:USERPROFILE\scoop" }
$json = Get-Content "$path\source_backup.json" -Raw | ConvertFrom-Json

foreach ($app in $json.apps) {
    $f = "$path\apps\$($app.Name)\current\install.json"
    $j = Get-Content $f -Raw | ConvertFrom-Json
    $j.bucket = $app.Source
    $j | ConvertTo-Json -Depth 10 | Set-Content $f
}
```

## 灵感来源

- [scoop-proxy-cn](https://github.com/lzwme/scoop-proxy-cn)
- [ScoopMaster](https://github.com/okibcn/ScoopMaster)

## 声明

> [!WARNING]
> 本仓库包含的应用信息仅从第三方仓库同步, 未逐一作可用性, 安全性验证, 请在安装选择时自行验证识别. 若有侵权请提 issues 处理.
