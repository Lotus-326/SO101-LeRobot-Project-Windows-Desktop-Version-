SO-Arm 舵机调试工具 | Seeed Studio Wiki  [#__docusaurus_skipToContent_fallback]Skip to main content
Collaborate with Seeed - [https://www.seeedstudio.com/blog/affiliate-program/]Creator, [https://www.seeedstudio.com/ranger-program/]Ranger, or [https://wiki.seeedstudio.com/contributors/]Contributor, there is always a role ideal for you!

# Lerobot 中 SO-ARM 的舵机调试工具
 Lerobot 中 SO-ARM 的舵机调试工具

## 简介[#简介]​
 舵机调试工具（Seeed_RoboController）是一款面向 Lerobot/SO-ARM 机械臂的图形化调试工具。通过该工具，你可以快速检测舵机状态、重新校准舵机 ID、写入中位值、单点控制舵机以及管理机械臂校准文件，从而更方便地完成主臂与从臂的组装、调试与维护。

## 一、安装[#一安装]​
 适用Windows,ubuntu,Mac系统
 1.首先下载仓库

```
git clone https://github.com/Seeed-Projects/Seeed_RoboController.git

```

 2.推荐安装在lerobot虚拟环境中，如需单独创立建议创立新的虚拟环境，避免污染系统 Python。

```
pip install -r requirements.txt

```

 3.检查环境，返回[OK] 环境检查通过，即可以运行项目

```
python setup.py

```

 4.进入
 运行启动交互式选择端口

```
python -m src.gui.factory_calibration_tool

```

 （可选）手动指定端口（如若端口被占用）

```
python -m src.gui.factory_calibration_tool --port1 /dev/ttyUSB0 --port2 /dev/ttyUSB1

```

## 二、开始使用（适用主臂和从臂）[#二开始使用适用主臂和从臂]​

### 1.检测舵机是否正常[#1检测舵机是否正常]​
 首先在串口选择上选择相应的端口号
 如若1-6号舵机均成功检测，则说明舵机正常被识别，基本功能正常

![](https://files.seeedstudio.com/wiki/robotics/projects/lerobot/debug_tool/debug_tool.webp)

 如若显示有相关舵机未识别到，首先检查连线是否正常，关掉页面重新进入，如若还是未识别到，则可能舵机ID号出现重复现象（可能是输入校准机械臂的指令不小心输入成了校准舵机的指令）此时需要将这些舵机ID进行重新校准

![](https://files.seeedstudio.com/wiki/robotics/projects/lerobot/debug_tool/02.png)

### 2.拆除舵机线束[#2拆除舵机线束]​
 首先拆除6号舵机和5号舵机的连接线束

![](https://files.seeedstudio.com/wiki/robotics/projects/lerobot/debug_tool/03.webp)

 而后拆除5号舵机和4号舵机的连接线束

![](https://files.seeedstudio.com/wiki/robotics/projects/lerobot/debug_tool/04.webp)

 拆除4号舵机和3号舵机的连接线束

![](https://files.seeedstudio.com/wiki/robotics/projects/lerobot/debug_tool/05.webp)

 拆除3号舵机和2号舵机的连接线束

![](https://files.seeedstudio.com/wiki/robotics/projects/lerobot/debug_tool/06.webp)

 拆除2号舵机和1号舵机的连接线束

![](https://files.seeedstudio.com/wiki/robotics/projects/lerobot/debug_tool/07.webp)

 拆除1号舵机和控制板的连接线束

![](https://files.seeedstudio.com/wiki/robotics/projects/lerobot/debug_tool/08.webp)

### 3.重新校准舵机ID[#3重新校准舵机id]​
 确保只有一个舵机连接到机械臂上
 （给舵机刷入ID时，由于是串口总线，如果存在重复id，例如将4改成6,总线上的所有4号舵机均会修改为6,所以需要将所有的舵机进行拆除逐个进行重新写入ID）
 例如可以通过如下方式将6号舵机与驱动板进行连接，其他舵机连接方式类似，可避免拆卸机械臂

![](https://files.seeedstudio.com/wiki/robotics/projects/lerobot/debug_tool/09.webp)

 如图所示，可以看到只识别到了4号舵机，但实际上我连接的是6号舵机，此时则说明我的舵机ID号是错误的,需要将舵机ID修改回6

![](https://files.seeedstudio.com/wiki/robotics/projects/lerobot/debug_tool/10.png)

 此时，可以点击4号舵机，将其ID修改为6，其他的舵机操作一致

![](https://files.seeedstudio.com/wiki/robotics/projects/lerobot/debug_tool/11.png)

 将舵机校准完成之后可以依次将线插入，即可完成

### 4.中位值写入舵机[#4中位值写入舵机]​

![](https://files.seeedstudio.com/wiki/robotics/projects/lerobot/debug_tool/12.jpg)

 1.点击串口中位测试，查看机械臂中位是否如上图所示，如果大致如上图所示，则机械臂的中位值正常
 2.如果不为上，把机械臂移动至中位，而后点击串口中位校准，机械臂会将当前位置当作中位写入舵机中
 3.点击串口失能电机，机械臂将会软掉需要用手进行辅助扶一下

![](https://files.seeedstudio.com/wiki/robotics/projects/lerobot/debug_tool/13.png)

### 5.单个舵机控制[#5单个舵机控制]​
 页面中默认位置的所有舵机的中位，如图所示

![](https://files.seeedstudio.com/wiki/robotics/projects/lerobot/debug_tool/14.png)

- 1.首先开启力矩，可一键开启所有力矩或单个舵机力矩，即可滑动进度条使得舵机达到相应的位置，但需要注意缓慢移动，而且由于舵机实际上的打印件会卡住相应的位置，所以实际上没法到达边缘位置，会有最大运动地方和最小运动地方，所以不能将进度条滑为0或最大。 关闭力矩后机械臂会软下。

![](https://files.seeedstudio.com/wiki/robotics/projects/lerobot/debug_tool/21.png)

 根据上图所示，开启力矩后运动相应的舵机会有变化

- 2.可以对单个舵机进行中位校准和清除舵机内部中位和最大最小位

- 3.以下是舵机信息
  Pos：位置
 V：电压
 T：温度
 Spd:速度
 Load：力矩
 Cur:电流
 Mov：运动状态
 Model：型号，权限
 Status：状态会显示正常或过流，过载

### 6、高级工具[#6高级工具]​
 可读取相应的寄存器地址数据并且写入相应数据
 可修改波特率
 可恢复出厂设置

![](https://files.seeedstudio.com/wiki/robotics/projects/lerobot/debug_tool/16.png)

[https://github.com/Seeed-Studio/wiki-documents/blob/docusaurus-version/sites/zh-CN/docs/Robotics/Robot_Kits/Lerobot/cn_Steering_Gear_Debugging_Tool.md]Edit this page
Last updated on Jun 29, 2026 by ZhuYuan

Loading Comments...

- [#简介]简介
- [#一安装]一、安装
- [#二开始使用适用主臂和从臂]二、开始使用（适用主臂和从臂）
- [#1检测舵机是否正常]1.检测舵机是否正常
- [#2拆除舵机线束]2.拆除舵机线束
- [#3重新校准舵机id]3.重新校准舵机ID
- [#4中位值写入舵机]4.中位值写入舵机
- [#5单个舵机控制]5.单个舵机控制
- [#6高级工具]6、高级工具

导航

- [/cn/Getting_Started/]快速开始
- [/cn/Sensor_Network/]传感器与感知
- [/cn/Network/]网络
- [/cn/Edge_Computing/]边缘计算
- [/cn/Cloud/]云端
- [https://solution.seeed.cc/]解决方案
生态

- [https://discord.com/invite/QqMgVwHT3X]Discord 社区
- [https://project.seeedstudio.com/]项目中心
- [https://www.seeedstudio.com/ecosystem/]合作伙伴
- [https://www.seeedstudio.com/distributors.html]经销商
快速指引

- [https://www.seeedstudio.com/]商店
- [https://www.seeedstudio.com/get_help/HowToGetHelp]如何获得帮助
- [https://support.seeedstudio.com/knowledgebase]常见问题
- [https://forum.seeedstudio.com/]论坛
- [https://www.seeedstudio.com/get_help/TechnicalSupport]技术支持
公司

- [https://www.seeedstudio.com/about-us/]关于我们
- [https://www.seeedstudio.com/join-us/]加入我们
- [https://www.seeedstudio.com/contacts]联系我们
- [https://www.seeedstudio.com/blog/2020/04/22/seeed-in-the-news/]媒体报道

Copyright © 2026 Seeed Studio, Inc. Built with Docusaurus.