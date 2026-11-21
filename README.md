# 创客互助中的披露边界与结对方案

社区共创场次、成员的授权留言及联络员回条。材料中的人、机构及经营记录是合成的。

每份资料为 UTF-8 JSON 数组。id 在同一份资料内唯一，原始文字按收到的形式保留。

- `data/messages.json`。活动协调员接收的成员原话。kind=成员回信表示本人回应，转引未必获得原发言人许可。
- `data/resources.json`。社区排班和保密记录。times 是成员报名的场次，选择同一人的两种活动会占用同一份可用容量。access 是资料所有方在报名系统已有的可见授权。
- `data/consents.json`。邀请回条。从时间线接入本次选择，accepted_for 指联络人谈到的场次和提议。
- `data/timeline.json`。协调员导出的先后回执。refs 同组在意见都收齐后处理。每份邀请的编号由受理时生成，报名时使用原来材料引用。

使用 Python 3.11 标准库，无需安装软件包或连接外部服务。

以下命令分别读取一份原始资料、检查资料中的字段与关联。

```sh
python3 -m json.tool data/messages.json
python3 -m unittest discover -s tests -v
```
