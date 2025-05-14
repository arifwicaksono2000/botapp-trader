import requests

# Session setup
session = requests.Session()

session.headers.update({
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8,id;q=0.7",
    "Content-Type": "application/x-www-form-urlencoded",
    "Origin": "https://secure.icmarkets.com",
    "Referer": "https://secure.icmarkets.com/Finance/TransferFunds",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "Upgrade-Insecure-Requests": "1",
})

# Your real session cookies
session.cookies.update({
    "ASP.NET_SessionId": "x10ipyvhgeatp0unbfv4uulr",
    ".ASPXAUTH": "4FB204409F070C89C98EE3B9BDFC5F506CF3B2FD243B02102E652B7E3F574AFCC2B5D123FB86E0CC4CA2E292639B246338166548632FAB3E9D989CCEC2D7D75988C4DDD7CC31135F95E48E3B5B4372FD75F2010E86268B4862FC7DA4FA8C7F11CA3A199A70B07B449F885CFBFC06541C14AB410711ADA9660DFCD04B4A28409BF860D91E00ACDE5419B8F28D410C57CC89807DE367CC03FCA123B99CABAB151312995AC466502DC29040D0D7EB8A27F5",
    "aws-waf-token": "7abcfa69-0265-4931-9277-71dd53f1264e:CQoAm9APILJBAAAA:2FKMTsajvxXLS5gOfH8WA8WV+8I4U0WG+vrjm1lmIs77iL4GshWicwDEVl98WpPy/emtMS0U1FUR5Gnkexx1GHaNoU0WiSwX/6sLhIhGlT4FjKalGamvJiaHnnhxtrbibosFRLlLbBtWV/XExvBeIeHo5yh5kOxVwyueJfNyhJ1ffDGXPBkRG6pwelqPlbnNcWIz2q4hMg==",
    "__RequestVerificationToken": "ll8_ZWQOdlC-kLFCrwf5gSKjqKJt7ZsQyEzrbwuMhIHbiumW3L398vqOqbtKaiJ7mwIzJJ67OuHPJqB7Ma9rTdjh3HlPHmwNhqPcloRTnj1ZoaeAsB9ukApsEKlfwM4u-ekiZsjekNmwUYcfxrQC-g2",
})

# Transfer payload (Replace with your desired amounts and IDs)
payload = {
    "BillSrcID": "12701014",
    "Amount": "1",
    "DestAmount": "0",
    "BillDestID": "12681696"
}

url = "https://secure.icmarkets.com/Finance/TransferFunds"

# Make POST request
response = session.post(url, data=payload)

# Print clearly the results
print(f"Status code: {response.status_code}")
print(f"Final URL after request: {response.url}")
print("Response snippet (500 chars):")
print(response.text[:500])

# Optional: Save response HTML to verify visually
with open("transfer_response.html", "w", encoding="utf-8") as f:
    f.write(response.text)
