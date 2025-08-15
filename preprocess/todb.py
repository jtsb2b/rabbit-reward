import os
from pymongo import MongoClient
from dotenv import load_dotenv
import logging
from typing import List, Union, Optional
import numpy as np
import pandas as pd
import re
from pythainlp.tokenize import word_tokenize
from openai import OpenAI
import ast
import json
from sentence_transformers import SentenceTransformer
load_dotenv(override=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# for name, value in os.environ.items():
#     print("{0}: {1}".format(name, value))

client_JTS = OpenAI(base_url=os.getenv("JAI_BASE_URL"), api_key=os.getenv("JAI_API_KEY"))
DATABASE_URL = os.getenv("MONGO_URL")
DB_NAME = "rabbit-reward"

from FlagEmbedding import BGEM3FlagModel

# model = BGEM3FlagModel('BAAI/bge-m3',  
#                        use_fp16=True) 



def get_collection(database_name, collection_name,mongo_uri = DATABASE_URL):
    """
    Connect to a MongoDB instance and return the specified collection.

    Args:
        database_name (str): Name of the MongoDB database.
        collection_name (str): Name of the collection in the database.
        mongo_uri (str): MongoDB connection URI (default is local MongoDB).

    Returns:
        pymongo.collection.Collection: The MongoDB collection object.
    """
    # Connect to MongoDB
    client = MongoClient(mongo_uri)
    
    # Access the database
    database = client[database_name]
    
    # Access the collection
    collection = database[collection_name]
    
    return collection

def to_db(database_url: str, db_name: str, collection_name: str, insert_type: str, data: Union[dict, List[dict]], metadata):
    """
    Inserts data into a MongoDB collection.

    Args:
        database_url (str): MongoDB connection URI.
        db_name (str): Name of the MongoDB database.
        collection_name (str): Name of the collection in the database.
        insert_type (str): Type of insertion ("one" or "many").
        data (Union[dict, List[dict]]): Data to insert into the collection.

    Returns:
        None
    """
    try:
        client = MongoClient(database_url)
        db = client[db_name]
        collection = db[collection_name]
        if metadata:
            for d in data:
                d.update(metadata)
                if isinstance(d.get("embedding"), np.ndarray):
                    d["embedding"] = d["embedding"].tolist()

        if insert_type == "many" and isinstance(data, list):
            if data:
                collection.insert_many(data)
                # logger.info("Data inserted successfully (many).")
            else:
                logger.warning("No data to insert (many).")
        elif insert_type == "one" and isinstance(data, dict):
            collection.insert_one(data)
            logger.info("Data inserted successfully (one).")
        else:
            logger.error("Invalid data or insert type.")
    except Exception as e:
        logger.error(f"Error connecting to MongoDB or inserting data: {e}")
    finally:
        client.close()
def tokenize(text):
    """
    Tokenize the input text using PyThaiNLP.
    :param text: Text to tokenize
    :return: List of tokens
    """
    return word_tokenize(text, engine="newmm",keep_whitespace=True)

BGE =  SentenceTransformer("BAAI/bge-m3")

def embed(text, input_type):
    """
    Generate embeddings using Voyage AI.
    :param text: Text to embed
    :param input_type: Input type for embedding (default is "text").
    :return: List of embedding vector.
    """
    #voyage = voyageai.Client()

    try:
        
        ## voyage
        #result = voyage.embed(text, model="voyage-3", input_type=input_type)
        #return result.embeddings
        # BGE
        response = BGE.encode(text)
        return response.tolist()
        

        if input_type == "document":
            response = client_JTS.embeddings.create(model = "jai-emb-passage",input = text).data
            return [i.embedding for i in response]
        elif input_type ==  "query":
            response = client_JTS.embeddings.create(model = "jai-emb-query",input = text).data
            return [response[0].embedding]
    except Exception as e:
        logger.error(f"Error occurred during embedding: {e}")
        return None
import ast
IMG_CAP_PATTERN = re.compile(r"<img-name>(.*?)</img-name>(?:\s*<caption>(.*?)</caption>)?", re.DOTALL | re.IGNORECASE)
def parse_images(answer_text: str):
    """
    Extract all <img-name>...</img-name> and optional <caption>...</caption> pairs.
    Returns a tuple: (cleaned_answer_without_tags, images_list)
    where images_list = [{'path': <img-name>, 'caption': <caption or ''>}, ...]
    """
    images = []
    for img_name, caption in IMG_CAP_PATTERN.findall(answer_text or ""):
        print(f"Found image: {img_name}, caption: {caption}")
        img_name_clean = (img_name or "").strip()
        caption_clean = (caption or "").strip()
        if img_name_clean:
            images.append({"path": img_name_clean, "caption": caption_clean})

    # Remove all occurrences from the answer for clean storage/embedding
    cleaned = IMG_CAP_PATTERN.sub("", answer_text or "")
    # Normalize whitespace after removal
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, images
def preprocess(path: str, collection_name: str):
    try:
        if not os.path.exists(path):
            raise ValueError(f"Invalid directory path: {path}")

        for root, _, file_names in os.walk(path):
            for file_name in file_names:
                if file_name.startswith("output"):
                    file_path = os.path.join(root, file_name)
                    print(f"Processing: {file_path}")
                    # quarter = root[-1]
                    # year = root[-6:-2]

                    with open(file_path, "r", encoding="utf-8") as f:
                        for line in f:
                            try: 
                                line = json.loads(line.strip())
                                if line.keys() == {"q","a"}:
                                    question = line["q"]
                                    raw_answer = line["a"]
                                    # seperate the image and caption from answer
                                    clean_answer, images = parse_images(raw_answer)
                                    full_content = (question + "\n" + clean_answer).strip()

                                    document_tokenized = tokenize(full_content)
                                    data = {
                                        "content": full_content,
                                        "content_tokenized": " ".join(document_tokenized),
                                        "source": file_name,
                                        "images": images
                                        # "quarter": quarter,
                                        # "year": year,
                                        # "type": "qa"
                                    }
                                    
                                    # Embedding
                                    data_to_embed = [data["content"]]
                                    embeddings = embed(data_to_embed, "document")
                                    
                                    if embeddings:
                                        data["embedding"] = embeddings[0]
                                        to_db(DATABASE_URL, DB_NAME, collection_name, "one", data, metadata=None)
                                        print(f"Successfully processed file: {file_name}")
                                elif line.keys() == {"text"}:
                                    text = line["text"]
                                    document_tokenized = tokenize(text)
                                    data = {
                                        "content": text,
                                        "content_tokenized": " ".join(document_tokenized),
                                        "source": file_name
                                        # "quarter": quarter,
                                        # "year": year,
                                        # "type": "text"
                                    }
                                    
                                    # Embedding
                                    data_to_embed = [data["content"]]
                                    embeddings = embed(data_to_embed, "document")
                                    
                                    if embeddings:
                                        data["embedding"] = embeddings[0]
                                        to_db(DATABASE_URL, DB_NAME, collection_name, "one", data, metadata=None)
                                        print(f"Successfully processed file: {file_name}")
                                else:
                                    logger.warning(f"Invalid JSON structure in {file_name}: {line}")
                            except json.JSONDecodeError as e:
                                
                                logger.error(f"JSON decode error in {file_name}: {e}")
                                print(line)
                    
    except ValueError as ve:
        logger.error(ve)
    except Exception as e:
        logger.error(f"An error occurred while processing files: {e}")
                    
                        
                        

                        
    




if __name__ == "__main__":
    preprocess("/Users/jullajakkarnjanaekarin/Documents/rabbit-reward/preprocess","rabbit-reward-segmented")
    # process_financial_ratio("/Users/jullajakkarnjanaekarin/Documents/SCG_test/financial_ratio.xlsx","SCG_financial_report_jai")
    # process_one_report("/Users/jullajakkarnjanaekarin/Documents/SCG_test/chunked_scg_one_report.md","SCG_financial_report_jai_report")
    