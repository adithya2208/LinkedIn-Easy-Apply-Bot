import time, random, os, csv, logging, re, yaml

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait  # type: ignore
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

from bs4 import BeautifulSoup
import pandas as pd
import pyautogui
from datetime import datetime, timedelta


def setupLogger(log):
    dt: str = datetime.strftime(datetime.now(), "%d_%m_%y %H_%M_%S ")

    if not os.path.isdir("./logs"):
        os.mkdir("./logs")

    logging.basicConfig(
        filename=("./logs/" + str(dt) + "applyJobs.log"),
        filemode="w",
        format="%(asctime)s::%(name)s::%(levelname)s::%(message)s",
        datefmt="./logs/%d-%b-%y %H:%M:%S",
    )
    log.setLevel(logging.DEBUG)

    consoleHandler = logging.StreamHandler()
    consoleHandler.setLevel(logging.DEBUG)
    consoleFormat = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s", "%H:%M:%S"
    )
    consoleHandler.setFormatter(consoleFormat)
    log.addHandler(consoleHandler)


def readParameters():
    with open("config.yaml", "r") as stream:
        try:
            parameters = yaml.safe_load(stream)
        except yaml.YAMLError as exc:
            raise exc

    assert len(parameters["positions"]) > 0
    assert len(parameters["locations"]) > 0
    assert parameters["username"] is not None
    assert parameters["password"] is not None
    assert parameters["phone_number"] is not None

    if "uploads" in parameters.keys() and type(parameters["uploads"]) == list:
        raise Exception(
            "uploads read from the config file appear to be in list format"
            + " while should be dict. Try removing '-' from line containing"
            + " filename & path"
        )

    log.info(
        {
            k: parameters[k]
            for k in parameters.keys()
            if k not in ["username", "password"]
        }
    )

    for key in parameters.get("uploads", {}):
        assert parameters.get("uploads", {})[key] != None
    return parameters


class EasyApplyBot:
    # MAX_SEARCH_TIME is 10 hours by default, feel free to modify it
    MAX_SEARCH_TIME: int = 10 * 60 * 60

    def __init__(
        self,
        username,
        password,
        phone_number,
        uploads={},
        filename="output.csv",
        blacklist=[],
        blackListTitles=[],
        positions=[],
        locations=[],
    ) -> None:
        self.browser = webdriver.Chrome(
            ChromeDriverManager(version="114.0.5735.90").install(),
            options=self.browser_options(),
        )
        self.wait = WebDriverWait(self.browser, 30)
        self.start_linkedin(username, password)

        self.phone_number = phone_number
        self.uploads = uploads

        self.filename = filename

        past_ids = self.get_appliedIDs(self.filename)
        self.appliedJobIDs = past_ids if past_ids != None else []

        self.blacklist = blacklist
        self.blackListTitles = blackListTitles

        self.positions = positions
        self.locations = locations

        self.start_time = time.time()
        self.successfulApplicationCount = 0

    def get_appliedIDs(self, filename):
        try:
            df: pd.DataFrame = pd.read_csv(
                filename,
                header=0,
                names=["timestamp", "jobID", "job", "company", "attempted", "result"],
                lineterminator="\n",
                encoding="utf-8",
            )

            df["timestamp"] = pd.to_datetime(
                df["timestamp"], format="%Y-%m-%d %H:%M:%S"
            )
            df = df[df["timestamp"] > (datetime.now() - timedelta(days=10))]
            jobIDs: list = list(df.jobID)
            log.info(f"{len(jobIDs)} previously applied (past 10 days) jobIDs found")
            return jobIDs
        except Exception as e:
            log.info(
                str(e) + "   jobIDs could not be loaded from CSV {}".format(filename)
            )
            return None

    def browser_options(self):
        options = Options()
        options.add_argument("--start-maximized")
        options.add_argument("--ignore-certificate-errors")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-extensions")

        # Disable webdriver flags or you will be easily detectable
        options.add_argument("--disable-blink-features")
        options.add_argument("--disable-blink-features=AutomationControlled")
        return options

    def start_linkedin(self, username, password):
        self.browser.set_window_position(1, 1)
        self.browser.maximize_window()
        log.info("Logging in.....Please wait   ")
        self.browser.get(
            "https://www.linkedin.com/login?trk=guest_homepage-basic_nav-header-signin"
        )
        try:
            user_field = self.browser.find_element("id", "username")
            pw_field = self.browser.find_element("id", "password")
            login_button = self.browser.find_element(
                "xpath", '//*[@id="organic-div"]/form/div[3]/button'
            )
            user_field.send_keys(username)
            user_field.send_keys(Keys.TAB)
            time.sleep(2)
            pw_field.send_keys(password)

            time.sleep(2)
            login_button.click()

            time.sleep(3)
        except TimeoutException:
            log.info(
                "TimeoutException! Username/password field or login button not found"
            )

    def start_apply(self):
        combos = [(a, b) for a in self.positions for b in self.locations]
        random.shuffle(combos)
        for item in combos:
            log.info(f"Applying to {item[0]}: {item[1]}")
            location = "&location=" + item[1]
            self.applications_loop(item[0], location)

    def applications_loop(self, position, location):
        startIndex = 0
        log.info("Looking for jobs.. Please wait..")

        while time.time() - self.start_time < self.MAX_SEARCH_TIME:
            try:
                log.info(
                    f"{(self.MAX_SEARCH_TIME - (time.time() - self.start_time)) // 60} minutes left in this search"
                )
                self.next_jobs_page(position, location, startIndex)

                randoTime = random.uniform(3.5, 4.9)
                time.sleep(randoTime)

                links = self.browser.find_elements("xpath", "//div[@data-job-id]")

                if len(links) == 0:
                    log.debug("No links found")
                    break

                jobIds = []

                for link in links:
                    children = link.find_elements(
                        "xpath", '//ul[@class="scaffold-layout__list-container"]'
                    )
                    for child in children:
                        if child.text not in self.blacklist:
                            temp = link.get_attribute("data-job-id")
                            jobId = temp.split(":")[-1]
                            jobIds.append(int(jobId))
                log.debug(
                    "Found "
                    + str(len(jobIds))
                    + " links! (Blacklisted links filtered out)"
                )
                startIndex += len(jobIds)
                jobIds = set(jobIds)
                jobIds: list = [x for x in jobIds if x not in self.appliedJobIDs]
                log.debug(
                    "Number of links after removing duplicates: " + str(len(jobIds))
                )

                for i, jobId in enumerate(jobIds):
                    self.get_job_page(jobId)
                    button = self.get_easy_apply_button()
                    result = False
                    if button:
                        if any(
                            word in self.browser.title for word in self.blackListTitles
                        ):
                            log.info(
                                "skipping this application, a blacklisted keyword was found in the job position"
                            )
                        else:
                            log.info(
                                f"\n successfulApplicationCount {self.successfulApplicationCount}:\n {self.browser.title}\n"
                            )
                            log.info("Clicking the EASY apply button")
                            button.click()
                            time.sleep(3)
                            result = self.send_resume()
                    else:
                        log.info("The button does not exist.")

                    if result:
                        self.successfulApplicationCount += 1

                    self.write_to_file(button, jobId, self.browser.title, result)

                    if (
                        self.successfulApplicationCount != 0
                        and self.successfulApplicationCount % 7 == 0
                    ):
                        sleepTime: int = random.randint(500, 900)
                        log.info(
                            f"""********count_application: {self.successfulApplicationCount}************\n\n
                                    Time for a nap - see you in:{int(sleepTime / 60)} min
                                ****************************************\n\n"""
                        )

                        time.sleep(sleepTime)
            except Exception as e:
                log.error(e)

    def write_to_file(self, button, jobID, browserTitle, result) -> None:
        def re_extract(text, pattern):
            target = re.search(pattern, text)
            if target:
                target = target.group(1)
            return target

        timestamp: str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        attempted: bool = False if button == False else True
        job = re_extract(browserTitle.split(" | ")[0], r"\(?\d?\)?\s?(\w.*)")
        company = re_extract(browserTitle.split(" | ")[1], r"(\w.*)")

        toWrite: list = [timestamp, jobID, job, company, attempted, result]
        if not os.path.exists("./" + self.filename):
            with open(self.filename, "w") as f:
                writer = csv.writer(f)
                writer.writerow(
                    ["timestamp", "jobID", "job", "company", "attempted", "result"]
                )

        with open(self.filename, "a") as f:
            writer = csv.writer(f)
            writer.writerow(toWrite)

    def get_job_page(self, jobID):
        job: str = "https://www.linkedin.com/jobs/view/" + str(jobID)
        self.browser.get(job)
        time.sleep(2)
        return

    def get_easy_apply_button(self):
        try:
            button = self.browser.find_elements(
                "xpath", '//button[contains(@class, "jobs-apply-button")]'
            )

            EasyApplyButton = button[0]

        except Exception as e:
            EasyApplyButton = False

        return EasyApplyButton

    def send_resume(self) -> bool:
        def is_present(button_locator) -> bool:
            return (
                len(self.browser.find_elements(button_locator[0], button_locator[1]))
                > 0
            )

        try:
            time.sleep(random.uniform(1.5, 2.5))
            next_locater = (
                By.CSS_SELECTOR,
                "button[aria-label='Continue to next step']",
            )
            review_locater = (
                By.CSS_SELECTOR,
                "button[aria-label='Review your application']",
            )
            submit_locater = (
                By.CSS_SELECTOR,
                "button[aria-label='Submit application']",
            )
            submit_application_locator = (
                By.CSS_SELECTOR,
                "button[aria-label='Submit application']",
            )
            error_locator = (By.XPATH, '//li-icon[@type="error-pebble-icon"]')
            upload_locator = upload_locator = (
                By.CSS_SELECTOR,
                "button[aria-label='DOC, DOCX, PDF formats only (5 MB).']",
            )
            follow_locator = (By.CSS_SELECTOR, "label[for='follow-company-checkbox']")

            submitted = False
            while True:
                # Upload Cover Letter if possible
                if is_present(upload_locator):
                    input_buttons = self.browser.find_elements(
                        upload_locator[0], upload_locator[1]
                    )
                    for input_button in input_buttons:
                        parent = input_button.find_element(By.XPATH, "..")
                        sibling = parent.find_element(
                            By.XPATH, "preceding-sibling::*[1]"
                        )
                        grandparent = sibling.find_element(By.XPATH, "..")
                        for key in self.uploads.keys():
                            sibling_text = sibling.text
                            gparent_text = grandparent.text
                            if (
                                key.lower() in sibling_text.lower()
                                or key in gparent_text.lower()
                            ):
                                input_button.send_keys(self.uploads[key])

                    # input_button[0].send_keys(self.cover_letter_loctn)

                    time.sleep(random.uniform(4.5, 6.5))

                # Click Next or submitt button if possible
                button: None = None
                buttons: list = [
                    next_locater,
                    review_locater,
                    follow_locator,
                    submit_locater,
                    submit_application_locator,
                ]
                for i, button_locator in enumerate(buttons):
                    if is_present(button_locator):
                        button: None = self.wait.until(
                            EC.element_to_be_clickable(button_locator)
                        )

                    if is_present(error_locator):
                        button = None
                        break

                    if button:
                        button.click()
                        time.sleep(random.uniform(1.5, 2.5))
                        if i in (3, 4):
                            submitted = True
                        if i != 2:
                            break
                if button == None:
                    log.info("Could not complete submission")
                    break
                elif submitted:
                    log.info("Application Submitted")
                    break

            time.sleep(random.uniform(1.5, 2.5))

        except Exception as e:
            log.info(e)
            log.info("cannot apply to this job")
            raise (e)

        return submitted

    def load_page(self, sleep=1):
        # TODO scroll on class="jobs-search-results-list (upto y=3500)
        element = self.browser.find_elements(
            By.XPATH,
            "//div[@class='scaffold-layout__list ']/div[starts-with(@class,'jobs-search-results-list')]",
        )
        if len(element) > 0:
            startPos = 0
            for i in range(10):
                startPos += 400
                self.browser.execute_script(
                    "arguments[0].scroll(0," + str(startPos) + ");", element[0]
                )
                time.sleep(sleep)
            return

        scroll_page = 0
        while scroll_page < 4000:
            self.browser.execute_script("window.scrollTo(0," + str(scroll_page) + " );")
            scroll_page += 200
            time.sleep(sleep)

        if sleep != 1:
            self.browser.execute_script("window.scrollTo(0,0);")

            time.sleep(sleep * 3)

        page = BeautifulSoup(self.browser.page_source, "lxml")
        return page

    def next_jobs_page(self, position, location, startIndex):
        self.browser.get(
            "https://www.linkedin.com/jobs/search/?f_LF=f_AL&keywords="
            + position
            + location
            + "&start="
            + str(startIndex)
        )


if __name__ == "__main__":
    log = logging.getLogger(__name__)
    setupLogger(log)

    parameters = readParameters()

    bot = EasyApplyBot(
        parameters["username"],
        parameters["password"],
        parameters["phone_number"],
        parameters.get("uploads", {}),
        parameters.get("output_filename", "output.csv"),
        parameters.get("blacklist", []),
        parameters.get("blackListTitles", []),
        [l for l in parameters["locations"] if l != None],
        [p for p in parameters["positions"] if p != None],
    )

    bot.start_apply()
