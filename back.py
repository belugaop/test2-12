import hashlib
import sqlite3
from typing import Optional
#import requests
from bs4 import BeautifulSoup
import lxml
import re
import json
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
import codecs
import cloudscraper
import threading

from info import KEY1, KEY2
MASTER_PASS = "Secret"


def get_token():
    requests = cloudscraper.create_scraper()
    res = requests.get(f"https://softdrives.in/api/v2/authorize?key1={KEY1}&key2={KEY2}")
    if res.json()["_status"] == "success":
        return res.json()["data"]["access_token"]
    return None


def gen_password(code: str, repeat=10) -> str:
    if repeat == 1:
        return hashlib.sha512(code.encode("utf-8")).hexdigest()
    return gen_password(
        hashlib.sha512((code + MASTER_PASS).encode("utf-8")
                       ).hexdigest(), repeat - 1
    )


class database:
    def __init__(self, database_path="users.db"):
        self.con = sqlite3.connect(database_path, check_same_thread=False)
        self.cur = self.con.cursor()
        self.cur.execute(
            """CREATE TABLE IF NOT EXISTS users (
                            telegram_id str unique,
                            sd text
                        )"""
        )
        self.con.commit()
        self.lock = threading.Lock()


    def __del__(self):
        self.con.commit()
        self.con.close()

    def get_sd(self, telegram_id):
        self.lock.acquire(1)
        self.cur.execute(
                "select sd from users where telegram_id = ?", (telegram_id,))
        self.lock.release()
        return self.cur.fetchone()

    def add_user(self, telegram_id, sd):
        self.lock.acquire(1)
        self.cur.execute(
            """INSERT INTO
                            users ( telegram_id , sd )
                            VALUES (?,?)""",
            (telegram_id, sd),
        )
        self.con.commit()
        self.lock.release()

    

    def delete_user(self, telegram_id):
        self.lock.acquire(1)
        self.cur.execute(
            """DELETE from
                            users where telegram_id = ?""",
            (telegram_id,),
        )
        self.lock.release()

        

    def update_user(self, telegram_id, sd):
        self.lock.acquire(1)

        self.cur.execute(
            """UPDATE users
                            SET sd = ?
                            WHERE telegram_id = ? """,
            (sd, telegram_id),
        )
        self.lock.release()

  

    def is_user_exist(self, telegram_id: str):
        return 0 if self.get_sd(telegram_id) == None else 1


class Result:
    def __init__(self, msg, code: int = 1, res=None) -> None:
        self.msg = msg
        self.code = code
        self.res = res

    def is_error(self) -> bool:
        return not bool(self.code)

    def is_success(self) -> bool:
        return bool(self.code)

    def message(self):
        return self.msg

    def result(self):
        return self.res


class Manager:
    def __init__(self) -> None:
        self.db = database()

    @staticmethod
    def _login(username: str, password: str) -> Result:
        requests = cloudscraper.create_scraper()
        filehosting = requests.get(
            "https://softdrives.in/account/login"
        ).cookies.get_dict()
        print(filehosting)
        requests = cloudscraper.create_scraper()
        response = requests.post(
            "https://softdrives.in/account/login",
            cookies=filehosting,
            data={
                "username": f"{username}",
                "password": f"{password}",
                "submitme": "1",
            },
        )
        if response.url == "https://softdrives.in/account":
            return Result(msg="logined succesfully", res=filehosting["filehosting"])
        return Result(msg="Username or password is worng", code=0)

    def _add_user_to_database(
        self, telegram_id: str, username: str, password: Optional[str]
    ) -> Result:
        if password == None:
            password = gen_password(telegram_id)
        res = Manager._login(username, password)
        if res.is_success():
            if self.db.is_user_exist(telegram_id):
                self.db.update_user(telegram_id, res.result())
                return Result(msg="User updated")
            self.db.add_user(telegram_id, res.result())
            return Result(msg="logined succesfully")
        return res

    def create_new_user(
        self,
        telegram_id: str,
        username: str,
        email: str,
        password: Optional[str] = None,
    ) -> Result:
        if self.db.is_user_exist(telegram_id):
            return Result(msg="User already been logined.", code=0)

        if password == None:
            password = gen_password(str(telegram_id))

        requests = cloudscraper.create_scraper()
        res = requests.get(
            f"https://softdrives.in/api/v2/account/create?access_token={get_token()}&username={username}&password={password}&email={email}&package_id=1"
        ).json()
        if res["_status"] == "success":
            self._add_user_to_database(telegram_id, username, password)
            return Result(msg=f"{res['response']} with\nusername={username}\npassword={password}", res=res["data"]["id"])
        return Result(msg=res["response"], code=0)

    def login_old_user(
        self, telegram_id: str, username: str, password: Optional[str] = None
    ) -> Result:
        return self._add_user_to_database(telegram_id, username, password)

    def delete_user_from_database(self, telegram_id: str) -> Result:
        self.db.delete_user(telegram_id)
        return Result(msg="User delete from database")

    def make_share_link(self, telegram_id: str, file_id: str) -> Result:
        requests = cloudscraper.create_scraper()
        return Result(
            msg="Created Share link",
            res=requests.post(
                "https://softdrives.in/account/ajax/generate_folder_sharing_url",
                data={'fileIds[]': file_id},
                headers={
                    "Cookie": f"filehosting={self.db.get_sd(telegram_id)[0]}"},
            ).json()["msg"],
        )

    def upload_file(self, telegram_id: str, file: str) -> Result:
        with codecs.open(file, "r", encoding="latin-1", errors="ignore") as fs:
            data = fs.read()

        boundary = "---SECTION---"
        while data.find(boundary) != -1:
            boundary = "-" + boundary + "-"

        payload = f'{boundary}\nContent-Disposition: form-data; name="files[]"; filename="{file}"\nContent-Type: {file.split(".")[-1]}\n\n{data}\n{boundary}--'
        requests = cloudscraper.create_scraper()
        response = requests.post(
            "https://softdrives.in/ajax/file_upload_handler",
            data=payload,
            headers={"Cookie": f"filehosting={self.db.get_sd(telegram_id)[0]}",
                    "Content-Type": f"multipart/form-data; boundary={boundary[2:]}"})
        try:
            if response.json()[0]["size"] == 0:
                return Result(msg="Invalid file", code=0)
        except Exception as e:
            return Result(msg="Something went wrong while uploading", res=e, code=0)

        return Result(
            msg="Uploaded sucessfully.",
            res=(
                response.json()[0]["url"],
                response.json()[0]["file_id"],
                self.make_share_link(
                    telegram_id, response.json()[0]["file_id"]).res,
            ),
        )

    def plot(self, xpoints, ypoints, msg, id):

        _, ax = plt.subplots()

        ax.set_xlabel("Day")
        ax.set_ylabel("Visits")
        ax.set_title(msg)

        ax = plt.figure().gca()
        ax.yaxis.set_major_locator(MaxNLocator(integer=True))
        plt.rcParams["figure.figsize"] = (9, 4)

        ax.tick_params(axis="x", colors="blue")
        ax.tick_params(axis="y", colors="green")

        plt.axis(ymin=0)

        plt.bar(xpoints, ypoints)
        ax.autoscale(enable=True)

        plt.savefig(str(id) + str(msg) + ".png",
                    bbox_inches="tight", pad_inches=0.2)

        plt.close()

    def get_table(self, data):
        table = "**Time       Visits      Percentage**__"
        for i in data.find_all("tr")[1:]:
            j = i.find_all("td")
            table += f"\n {j[0].text:<14}{j[1].text:<14}{j[2].text}"
        return table + "__"

    def file_info(self, telegram_id, file_id):
        requests = cloudscraper.create_scraper()
        res = requests.get(f"https://softdrives.in/{file_id}~s", headers={
                           "Cookie": f"filehosting={self.db.get_sd(telegram_id)[0]}"}).text
        html = BeautifulSoup(res, "lxml")

        data = str(html.html.body.div.script)
        dates = ["last24hours", "last7days", "last30days", "last12months"]
        m = re.findall("chartData = (.+?);", data)
        d = 0
        images = []
        for i in m:
            data = json.loads(i)
            xpoints = data["labels"]
            ypoints = [int(i) for i in data["datasets"][0]["data"]]

            _, ax = plt.subplots()

            ax.set_xlabel("Day")
            ax.set_ylabel("Visits")
            ax.set_title(dates[d])

            ax = plt.figure().gca()
            ax.yaxis.set_major_locator(MaxNLocator(integer=True))
            plt.rcParams["figure.figsize"] = (9, 4)

            ax.tick_params(axis="x", colors="blue")
            ax.tick_params(axis="y", colors="green")

            plt.axis(ymin=0)

            plt.bar(xpoints, ypoints)
            ax.autoscale(enable=True)

            plt.savefig(
                str(file_id) + str(dates[d]) + ".png", bbox_inches="tight", pad_inches=0.2)

            images.append(file_id + dates[d] + ".png")
            d += 1

        table = []
        tables = html.find_all("table")
        for i in range(4):
            table.append(self.get_table(tables[i]))

        return Result(msg="img and table", res=(table, images))

    def user_info(self, telegram_id: str) -> Result:
        requests = cloudscraper.create_scraper()
        reward = BeautifulSoup(
            requests.get(
                "https://softdrives.in/account/rewards",
                headers={
                    "Cookie": f"filehosting={self.db.get_sd(telegram_id)[0]}"},
            ).text,
            "lxml",
        ).table.tbody.find_all("td")

        requests = cloudscraper.create_scraper()
        data = requests.post(
            "https://softdrives.in/account/ajax/get_account_file_stats",
            headers={
                "Cookie": f"filehosting={self.db.get_sd(telegram_id)[0]}"},
        ).json()

        return Result(
            msg="User info",
            res={
                "Total Files": data["totalRootFiles"],
                "Size Used": data["totalActiveFileSizeFormatted"],
                "Size Available": data["totalFileStorageFormatted"],
                "Percentage Of Used": data["totalStoragePercentage"],
                "Balance": reward[1].text,
                "Paid": reward[3].text,
                "Pending Payment": reward[5].text,
                "Traffic Available Today": reward[7].text,
            },
        )

