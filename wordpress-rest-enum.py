# wordpress-rest-enum.py

import requests
import json
import argparse
import logging
import urllib3
import re

urllib3.disable_warnings()

# Argument parsing
parser = argparse.ArgumentParser()
# Argument group, select either website or input file
group = parser.add_mutually_exclusive_group(required=True)
group.add_argument(
    "-w", "--website", help="Website to check.", action="store", type=str
)
group.add_argument(
    "-i", "--input-file", help="Input file containing list of websites", type=str
)
parser.add_argument_group(group)
parser.add_argument(
    "--log-level",
    default=logging.WARNING,
    type=lambda x: getattr(logging, x),
    help="Configure the logging level.",
)
parser.add_argument(
    "-m",
    "--media",
    help="Fetch media",
    action=argparse.BooleanOptionalAction,
    required=False,
)
parser.add_argument(
    "-po",
    "--posts",
    help="Fetch posts",
    action=argparse.BooleanOptionalAction,
    required=False,
)
parser.add_argument(
    "-pa",
    "--pages",
    help="Fetch pages",
    action=argparse.BooleanOptionalAction,
    required=False,
)
parser.add_argument(
    "-u",
    "--users",
    help="Fetch users",
    action=argparse.BooleanOptionalAction,
    required=False,
)
parser.add_argument(
    "-c",
    "--comments",
    help="Fetch comments",
    action=argparse.BooleanOptionalAction,
    required=False,
)
parser.add_argument(
    "-im",
    "--ignoreImages",
    help="Filter out extensions commonly associated with images and video",
    action=argparse.BooleanOptionalAction,
    required=False,
)
parser.add_argument(
    "-be",
    "--block-extensions",
    help="Additional comma-separated file extensions to block (e.g. 'pdf,doc,docx')",
    type=str,
    required=False,
)
parser.add_argument(
    "-o",
    "--output-file",
    help="Output file to save the results.",
    type=str,
    required=False,
)

parser.add_argument(
    "-p",
    "--proxy",
    help="Address to the proxy server (e.g. socks5://127.0.0.1:9050)",
    type=str,
    required=False,
)

parser.add_argument(
    "--json",
    help="Output in JSON format",
    action="store_true",
    required=False,
)

cliArgs = parser.parse_args()

# Logging
logging.basicConfig(level=cliArgs.log_level)

# Globals
HEADERS = {"User-Agent": "WordPress Testing"}
# Create a single session for reuse
SESSION = requests.Session()
SESSION.headers.update(HEADERS)
SESSION.verify = False

if cliArgs.proxy:
    SESSION.proxies = {
        "http": cliArgs.proxy,
        "https": cliArgs.proxy,
    }

API_TIMEOUT = 3  # 3 seconds timeout for API requests

# Compile regex patterns once
IMAGE_EXTENSIONS_PATTERN = re.compile(
    r"\.(jpg|gif|jpeg|png|svg|tiff|webm|webp|mp4|mov|avif|mp3|ttf|woff|eot|woff2|heic|tif|ogg|m4v|bmp|ico)$",
    re.IGNORECASE,
)


def requestRESTAPIComments(website: str, fetchPage: int, timeout=API_TIMEOUT) -> json:
    perPage = 100
    apiRequest = (
        f"{website}/wp-json/wp/v2/comments?per_page={perPage}&page={str(fetchPage)}"
    )
    results = []
    try:
        download = SESSION.get(apiRequest, timeout=timeout)
        if download.status_code == 200:
            # WordPress API returns mixed HTML and JSON in the users API endpoint.
            # Remove all content to the first `[` indicating the beginning of JSON data.
            content = "[" + "[".join(download.text.split("[")[1:])
            comments = json.loads(content)
            for comment in comments:
                try:
                    newComment = {
                        "name": comment["author_name"],
                        "date": comment["date"],
                        "link": comment["link"],
                    }
                    results.append(newComment)
                except Exception as err:
                    print(f"Unexpected {err=}, {type(err)=}")
                    raise
            fetchPage = fetchPage + 1
            if len(comments) > 0:
                results += requestRESTAPIComments(website, fetchPage)
    except requests.exceptions.ReadTimeout as e:
        logging.warning(f"ReadTimeout for comments API: {e}")
        return results  # Return partial results and continue
    except:
        raise

    return results


def requestRESTAPIUsers(website: str, fetchPage: int, timeout=API_TIMEOUT) -> json:
    perPage = 100
    apiRequest = (
        f"{website}/wp-json/wp/v2/users?per_page={perPage}&page={str(fetchPage)}"
    )
    results = []
    try:
        download = SESSION.get(apiRequest, timeout=timeout)
        if download.status_code == 200:
            content = download.text
            users = json.loads(content)
            for user in users:
                try:
                    newUser = {"name": user["name"], "username": user["slug"]}
                    results.append(newUser)
                except Exception as err:
                    print(f"Unexpected {err=}, {type(err)=}")
                    raise
            fetchPage = fetchPage + 1
            if len(users) > 0:
                results += requestRESTAPIUsers(website, fetchPage)
    except requests.exceptions.ReadTimeout as e:
        logging.warning(f"ReadTimeout for users API: {e}")
        return results  # Return partial results and continue
    except:
        raise
    return results


def requestRESTAPI(
    type: str, website: str, fetchPage: int, timeout=API_TIMEOUT
) -> list:
    perPage = 100

    try:
        apiRequest = (
            f"{website}/wp-json/wp/v2/{type}?per_page={perPage}&page={str(fetchPage)}"
        )
        results = []
        download = SESSION.get(apiRequest, timeout=timeout)
        if download.status_code == 200:
            content = download.text
            if content is not None:
                apiResponse = json.loads(content)
                for typeReturn in apiResponse:
                    try:
                        results.append(typeReturn["guid"]["rendered"])
                    except Exception as err:
                        print(f"Unexpected {err=}, {type(err)=}")
                        raise
                fetchPage = fetchPage + 1
                if len(apiResponse) > 0:
                    results += requestRESTAPI(type, website, fetchPage)
    except requests.exceptions.ReadTimeout as e:
        logging.warning(f"ReadTimeout for {type} API: {e}")
        return results  # Return partial results and continue
    except:
        raise

    return results


def format_plain_text(result):
    lines = []
    lines.append(f"Website: {result['website']}")
    if "users" in result and result["users"]:
        lines.append("Users:")
        for user in result["users"]:
            lines.append(f"  Name: {user['name']}, Username: {user['username']}")
    if "posts" in result and result["posts"]:
        lines.append("Posts:")
        for post in result["posts"]:
            lines.append(f"  {post}")
    if "pages" in result and result["pages"]:
        lines.append("Pages:")
        for page in result["pages"]:
            lines.append(f"  {page}")
    if "media" in result and result["media"]:
        lines.append("Media:")
        for media in result["media"]:
            lines.append(f"  {media}")
    if "comments" in result and result["comments"]:
        lines.append("Comments:")
        for comment in result["comments"]:
            lines.append(f"  Name: {comment['name']}, Date: {comment['date']}, Link: {comment['link']}")
    return "\n".join(lines)


def main():
    websites = []
    if cliArgs.input_file:
        with open(cliArgs.input_file, "r") as f:
            websites_from_file = f.readlines()
            for website in websites_from_file:
                website = website.strip()
                websites.append(website)
    else:
        websites.append(cliArgs.website)
    fetchPage = 1

    cnt = 0
    try:
        for website in websites:
            logging.info(f"Processing {website}")
            result = {}
            result["website"] = website
            found = False
            if cliArgs.posts:
                result["posts"] = requestRESTAPI("posts", website, fetchPage)
                if len(result["posts"]) > 0:
                    found = True
            if cliArgs.pages:
                result["pages"] = requestRESTAPI("pages", website, fetchPage)
                if len(result["pages"]) > 0:
                    found = True
            if cliArgs.comments:
                result["comments"] = requestRESTAPIComments(website, fetchPage)
                if len(result["comments"]) > 0:
                    found = True
            if cliArgs.media:
                result["media"] = requestRESTAPI("media", website, fetchPage)
                if cliArgs.ignoreImages or cliArgs.block_extensions:
                    newMedia = []
                    # Base extensions to ignore if ignoreImages is True
                    extensions_to_ignore = (
                        IMAGE_EXTENSIONS_PATTERN if cliArgs.ignoreImages else None
                    )

                    # Add additional extensions if specified
                    if cliArgs.block_extensions:
                        additional_extensions = "|".join(
                            ext.strip() for ext in cliArgs.block_extensions.split(",")
                        )
                        if extensions_to_ignore:
                            extensions_to_ignore = re.compile(
                                f"({extensions_to_ignore.pattern}|{additional_extensions})$",
                                re.IGNORECASE,
                            )
                        else:
                            extensions_to_ignore = re.compile(
                                f"\.({additional_extensions})$", re.IGNORECASE
                            )

                    for url in result["media"]:
                        # Remove trailing slash if present before checking extension
                        url_to_check = url.rstrip("/")
                        if not extensions_to_ignore.search(url_to_check):
                            newMedia.append(url)
                    result["media"] = newMedia
                if len(result["media"]) > 0:
                    found = True
            if cliArgs.users:
                result["users"] = requestRESTAPIUsers(website, fetchPage)
                if len(result["users"]) > 0:
                    found = True
            if not found:
                logging.info(json.dumps({"message": "no results", "target": website}))
            else:
                if cliArgs.json:
                    output = json.dumps(result)
                else:
                    output = format_plain_text(result)
                if cliArgs.output_file:
                    with open(cliArgs.output_file, "a") as f:
                        if cnt > 0:
                            f.write("\n")
                        f.write(output)
                else:
                    print(output)
            cnt += 1
    except json.JSONDecodeError as e:
        logging.warning(f"JSON decode error {e=}, {type(e)=}")
    except urllib3.exceptions.MaxRetryError as e:
        logging.warning(f"Max retries exceeded {e=}, {type(e)=}")
    except requests.exceptions.ConnectionError as e:
        logging.warning(f"Connection error {e=}, {type(e)=}")
    except requests.exceptions.InvalidSchema as e:
        logging.warning(f"Invalid schema {e=}, {type(e)=}")
    except requests.exceptions.ReadTimeout as e:
        logging.warning(f"ReadTimeout {e=}, {type(e)=}")
    except urllib3.exceptions.ReadTimeoutError as e:
        logging.warning(f"Timeout {e=}, {type(e)=}")
    except Exception as e:
        logging.warning(f"Unexpected {e=}, {type(e)=}")
    finally:
        SESSION.close()


if __name__ == "__main__":
    main()
