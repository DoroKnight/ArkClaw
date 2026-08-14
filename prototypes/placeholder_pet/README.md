# 程序化桌宠原型

这个目录保存第一阶段之前使用的程序化桌宠原型启动方式。它不加载 Spine DLL、角色
manifest 或外部贴图，只显示 `PlaceholderPetRenderer` 绘制的原始角色。

`PlaceholderPetRenderer` 的实现仍留在正式 Python 包中，因为它同时是生产桌宠加载失败时的
安全 fallback（安全降级）。这里不复制第二份渲染源码，避免原型与安全 fallback 产生两套
行为不一致的实现。

启动前请先退出已经运行的正式桌宠，因为正式版和原型共享单实例保护。

在仓库工作树根目录运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\prototypes\placeholder_pet\start_placeholder_pet.ps1
```

需要观察错误输出时使用控制台模式：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\prototypes\placeholder_pet\start_placeholder_pet.ps1 -Console
```

只验证启动器是否导入当前工作树代码，不打开窗口：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\prototypes\placeholder_pet\start_placeholder_pet.ps1 -ValidateOnly
```

原型的历史设计说明见
[占位桌宠窗口文档](../../docs/pet/pet_window_placeholder.md)。
