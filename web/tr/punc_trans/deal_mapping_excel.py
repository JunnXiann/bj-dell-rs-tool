import pandas as pd
import pymongo

# 连接到本地 MongoDB 服务器
client = pymongo.MongoClient("mongodb://localhost:27017/")
# 创建一个数据库
db = client["jsz_cbeta_maps"]
# 创建一个集合
collection = db["jsz_cbeta_mapping_excels"]

# 读取 Excel 文件
excel_file = pd.ExcelFile(
    "web/tr/punc_trans/mapping_excels/径山藏对应CBETA经号及标点-20250310.xlsx"
)
# 获取指定工作表中的数据
df = excel_file.parse("Sheet1")

# 将 DataFrame 转换为字典列表
data = df.to_dict(orient="records")

# 将数据插入到 MongoDB 集合中
collection.insert_many(data)

# 查询集合中的所有文档
results = collection.find()

# 按行打印数据，并打印指定字段的值
for result in results:
    print("整行内容:", result)
    # 请将 'column_name' 替换为你实际想要打印的字段名
    print("指定字段内容:", result.get("经号1"))
    print("-" * 50)

# 关闭连接
client.close()

print("end")
