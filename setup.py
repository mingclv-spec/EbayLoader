from setuptools import setup, find_packages

setup(
    name="ebayloader",
    version="0.1.0",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "click>=8.0",
        "requests>=2.28",
        "PyYAML>=6.0",
        "rich>=13.0",
        "python-dotenv>=1.0",
        "Pillow>=10.0",
    ],
    entry_points={
        "console_scripts": [
            "ebay=ebayloader.cli:main",
        ],
    },
    python_requires=">=3.8",
    author="Ming",
    description="Batch upload products to sell on eBay",
    keywords="ebay, selling, batch, cli",
)
