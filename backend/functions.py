
import os
import logging
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient # IMPORT AsyncMongoClient
from pythainlp.tokenize import word_tokenize # Moved import here
import models # Keep standard import
import asyncio
from typing import Optional, Dict
# import time # No longer needed for reranker
# import numpy as np # No longer needed for reranker
# import onnxruntime as ort # No longer needed for reranker
# from transformers import AutoTokenizer # No longer needed for reranker

# Load environment variables
load_dotenv(override=True)

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# MongoDB Configuration
DATABASE_URL = os.getenv("MONGO_URL")
# DATABASE_URL = "mongodb://rabbit_reward:rabbit_password@host.docker.internal:27017/?directConnection=true"
DB_NAME = "rabbit-reward"
DEFAULT_VECTOR_INDEX = "default" # Example: Make configurable
DEFAULT_KEYWORD_INDEX = "default" # Example: Make configurable

class MongoHybridSearch:
    def __init__(self, database_name=DB_NAME, mongo_uri=DATABASE_URL):
        """
        Initialize MongoDB connection and embedder.
        """
        try:
            self.client = AsyncIOMotorClient(mongo_uri)
            self.database = self.client[database_name]
            # Consider making collection name configurable
            self.collection = self.database["rabbit-reward"]
            # self.collection_fact = self.database["SCG_financial_report_jai"]
            self.llm_analyzer = models.LLMFinanceAnalyzer()
            self.embedder = models.Embedder() # Instantiate Embedder class from models
            logger.info("MongoHybridSearch initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize MongoHybridSearch: {e}")
            raise # Re-raise exception to prevent app from starting with bad config

    async def search_documents(self, query: str) -> list[str]:
        """
        Find relevant data for each (subquery, original_query, quarter, year).
        Args:
            query_list (list): List of tuples (subquery, original_query, quarter, year).
        Returns:
            list: List of lists, where each inner list contains relevant document content strings.
                  Returns empty list if an error occurs during the overall search process.
        """
        try:
            all_docs_content = []
            
            # for subquery, subkeyword, quarter, year in query_list: # Unpack the tuple
                # Pass configured index names
            result_content = await self.atlas_hybrid_search(collection_name = self.collection,
                query=query,
                
                top_k=100, # Consider making configurable
                exact_top_k=15, # Consider making configurable
                vector_index_name=DEFAULT_VECTOR_INDEX,
                keyword_index_name=DEFAULT_KEYWORD_INDEX,
                
            )
            all_docs_content.append(result_content)
            return result_content
        except Exception as e:
            logger.error(f"Error in search_documents: {e}")
            return [] # Return empty list on failure

    async def atlas_hybrid_search(self, collection_name :str, query: str, top_k: int, exact_top_k: int,
                            vector_index_name: str, keyword_index_name: str,
                            ) -> list[Dict]:
        """
        Perform hybrid search using Atlas Vector Search & Keyword Search.
        Returns a list of document content strings.
        """
        try:
            # Ensure quarter and year are strings for MongoDB query
            # quarter_str = [str(quarter)]
            # year_str = [str(year)]
            # if collection_name == "fact":
            #     collection  = self.collection_fact
            # elif collection_name == "report":
            #     collection = self.collection_report
            #     top_k = 15 # For report collection, we might want fewer results
            #     exact_top_k = 7
            # else:
            #     pass

            query_vector = await self.embedder.embed(query, "query")
            print(len(query_vector))
            # query_vector = query_vector[0]
            if not query_vector:
                 logger.error(f"Failed to get embedding for query: {query}")
                 return []
            
            # Perform vector search
            vector_pipeline = [
                {
                    "$vectorSearch": {
                        "queryVector": query_vector,
                        "path": "embedding", # Ensure 'embedding' is the correct field name
                        "numCandidates": 10000, # Consider making configurable
                        "limit": top_k,
                        "index": vector_index_name,
                        # "filter": {
                        #     "$and": [
                        #         {"quarter": {"$in": quarter_str}},
                        #         {"year": {"$in": year_str}}
                        #     ]
                        # }
                    }
                },
                {"$project": {"_id": 1, "content": 1,"images":1, "embedding":1, "score": {"$meta": "vectorSearchScore"}}}
            ]
            vector_results_cursor = self.collection.aggregate(vector_pipeline)
            vector_results = await vector_results_cursor.to_list(length=top_k)
            logger.info(f"Vector search found {len(vector_results)} results for query: '{query}'")


            # Tokenize query for keyword search using PyThaiNLP
            query_tokens = word_tokenize(query, engine="newmm", keep_whitespace=False)
            logger.info(f"Keyword search tokens: {query_tokens}")

            # Perform keyword search (Atlas Search)
            keyword_pipeline = [
                {
                    "$search": {
                        "index": keyword_index_name,
                        "text": {
                            "query": query_tokens,
                            "path": "content_tokenized" 
                            }
                    }
                },
                # {
                #     "$match": {
                #         "$and": [
                #             {"quarter": {"$in": quarter_str}},
                #             {"year": {"$in": year_str}}
                #         ]
                #     }
                # },
                {
                    "$project": {
                        "_id": 1,
                        "content": 1,
                        "images":1,
                        "embedding":1,
                        "score": {"$meta": "searchScore"}
                    }
                },
                {"$limit": top_k}
            ]
            keyword_results_cursor = self.collection.aggregate(keyword_pipeline)
            keyword_results = await keyword_results_cursor.to_list(length=top_k) # Using length for explicit limit from cursor
            logger.info(f"Keyword search found {len(keyword_results)} results for query: '{query}'")


            # Apply Weighted Reciprocal Rank Fusion (WRRF)
            # Prepare results in the expected format for WRRF: list of dicts with _id and content
            print(f"Vector results: {len(vector_results)}, Keyword results: {len(keyword_results)}")
            vec_docs = [{"_id": str(doc["_id"]), "content": doc.get("content", ""), "images" : doc.get("images",""), "embedding": doc.get("embedding","")} for doc in vector_results]
            key_docs = [{"_id": str(doc["_id"]), "content": doc.get("content", ""), "images" : doc.get("images",""), "embedding": doc.get("embedding","")} for doc in keyword_results]

            # Handle potential missing 'content' key more robustly
            # Ensure content is string
            for doc_list in [vec_docs, key_docs]:
                 for doc in doc_list:
                     if not isinstance(doc["content"], str):
                         logger.warning(f"Document content is not a string (ID: {doc['_id']}), converting.")
                         doc["content"] = str(doc["content"])


            fused_documents = self.weighted_reciprocal_rank([vec_docs, key_docs], top_k)
            if len(fused_documents) < exact_top_k:
                exact_top_k = len(fused_documents) 
            # fused_documents = fused_documents[:exact_top_k] 
            
            # async def check_and_get_relevant(doc: Dict) -> Optional[Dict]:
            #     # Use a helper to run the classification and return the doc if relevant
            #     is_relevant = await self.llm_analyzer.classify_relevance(query=query, document_content=doc.get("content", ""))
            #     if is_relevant:
            #         return doc
            #     return None
            # tasks = [check_and_get_relevant(doc) for doc in fused_documents]
            # relevance_results = await asyncio.gather(*tasks)

            # # Filter out None values (non-relevant docs)
            # relevant_docs = [doc for doc in relevance_results if doc is not None]
            # logger.info(f"Found {len(relevant_docs)} relevant documents after LLM classification (out of {len(fused_documents)}).")
            # if len(relevant_docs) < exact_top_k:
            #     exact_top_k = len(relevant_docs) 
            # Return only the content strings, limited to exact_top_k
            return fused_documents[:exact_top_k]

        except Exception as e:
            logger.error(f"Error in atlas_hybrid_search for query '{query}': {e}", exc_info=True)
            return []

    def weighted_reciprocal_rank(self, doc_lists: list[list[dict]], top_k: int) -> list[dict]:
        """
        Apply Weighted Reciprocal Rank Fusion (WRRF) to rank results.
        Args:
            doc_lists: List of lists of documents. Each inner list is from one search method.
                       Each document is a dict with at least '_id' and 'content'.
            top_k: The maximum number of documents to return after fusion.
        Returns:
            List of fused documents, sorted by RRF score, limited by top_k.
        """
        try:
            # Ensure doc_lists is not empty and contains lists
            if not doc_lists or not all(isinstance(dl, list) for dl in doc_lists):
                logger.warning("WRRF called with invalid doc_lists.")
                return []

            # Configuration for WRRF
            c = 60 # Constant for rank penalty, tunable
            weights = [1.0, 1.0] # Vector search weight, keyword search weight - Tunable

            if len(doc_lists) != len(weights):
                 # Fallback if weights don't match lists (e.g., one search returned nothing)
                 # This basic handling might need refinement based on desired behavior
                 weights = [1.0] * len(doc_lists)
                 logger.warning(f"Number of doc lists ({len(doc_lists)}) != number of weights ({len(weights)}). Using equal weights.")
                 # raise ValueError("Number of rank lists must be equal to the number of weights.")


            # Use a dictionary to map unique content to its document dict and accumulate scores
            # This handles cases where the same doc appears in multiple lists or multiple times
            rrf_scores = {} # content -> {'score': float, 'doc': dict}

            for doc_list, weight in zip(doc_lists, weights):
                processed_ids_in_list = set() # Track IDs within the current list to handle duplicates from the *same* source
                for rank, doc in enumerate(doc_list, start=1):
                    doc_id = doc.get("_id")
                    content = doc.get("content")

                    # Basic validation
                    if not doc_id or content is None:
                        logger.warning(f"Skipping doc with missing ID or content in WRRF: {doc}")
                        continue
                    if not isinstance(content, str): # Ensure content is string for keying
                        content = str(content)
                        doc["content"] = content # Update doc dict too

                    # Only score the first occurrence of a document *within the same list*
                    if doc_id in processed_ids_in_list:
                        continue
                    processed_ids_in_list.add(doc_id)


                    # Calculate RRF score contribution
                    rank_score = weight * (1.0 / (rank + c))

                    # Accumulate score or add new entry
                    if content in rrf_scores:
                        rrf_scores[content]['score'] += rank_score
                    else:
                        # Store the first encountered 'doc' dict for this content
                        rrf_scores[content] = {'score': rank_score, 'doc': doc}


            # Sort documents based on accumulated RRF score
            # We sort the items (content, score_data) by score
            sorted_items = sorted(rrf_scores.items(), key=lambda item: item[1]['score'], reverse=True)
            
            # Return the document dictionaries from the sorted items, limited by top_k
            return [item[1]['doc'] for item in sorted_items[:top_k]]

        except Exception as e:
            logger.error(f"Error in weighted_reciprocal_rank: {e}", exc_info=True)
            return []
        
# Example usage (optional, for testing)
if __name__ == "__main__":
    # To test async code, you need an asyncio event loop
    async def main_test():
        print("Testing MongoHybridSearch...")
        try:
            search_engine = MongoHybridSearch()
            query_example = 'สถานีไหนไม่ได้ร่วมการรับพอยต์ Rabbit Rewards'
            
            results = await search_engine.search_documents(query_example) # Await here
            print("\nSearch Results:")
            if results:
                print(results)
            else:
                print("Search failed or returned no results.")

        except Exception as e:
            print(f"An error occurred during testing: {e}")

    # Run the async test function
    asyncio.run(main_test())