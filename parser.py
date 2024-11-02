import requests
from bs4 import BeautifulSoup


def get_page(base_url, pages=1):
    for page_num in range(1, pages + 1):
        current_url = f'{base_url}'

        page_data = process_page(current_url)

        display_products(page_num, page_data)


def process_page(current_url):
    products_data = []

    response = requests.get(current_url)
    soup = BeautifulSoup(response.content, "lxml")

    # Находим все товары на странице
    products_names = soup.find_all("div", class_="l-product__name")
    products_prices = soup.find_all("div", class_="l-product__price-base")

    for i in range(len(products_names)):
        title = products_names[i].find('span', itemprop="name").text
        price = "".join(filter(str.isdigit, products_prices[i].text))

        products_data.append({
            "title": title,
            "price": price
        })

    return products_data


def display_products(page_num, products):
    print(f"\nСобраны данные со страницы {page_num}")
    print(f"{'№':<5}{'Название':<80}{'Цена':>10}")
    print("-" * 95)
    for i, product in enumerate(products, 1):
        print(f"{i:<5}{product['title']:<90}{product['price']:>10}")


url = "https://www.maxidom.ru/catalog/kran-buksy/"
get_page(url)
