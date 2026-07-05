import pymysql
try:
    c = pymysql.connect(host="172.18.175.122", port=3308, user="superclaw", password="GEW3fHhi8KxwhMwM", database="superclaw")
    print("OK")
    c.close()
except Exception as e:
    print("FAIL", e)
