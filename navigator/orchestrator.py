# Navigator Orchestrator
# Implements the multi-model approach outlined in plan.md

from navigator.brain.code_assistant import CodeAssistant
from navigator.brain.planner import TaskPlanner
from navigator.brain.api_reverse_engineer import APIReverseEngineer
from navigator.memory.semantic_indexer import SemanticIndexer
from navigator.web_navigator import WebNavigator
from core.plugins.selenium_manager import SeleniumManager
from rich.console import Console

console = Console()

class Navigator:
    def __init__(self, ollama_client, selenium_manager: SeleniumManager = None):
        """
        Initialize the Navigator orchestrator to coordinate all models.
        
        Args:
            ollama_client: Client for communicating with Ollama API
            selenium_manager: Optional SeleniumManager instance
        """
        self.ollama_client = ollama_client
        
        # Create a new SeleniumManager if none was provided
        if selenium_manager is None:
            self.selenium_manager = SeleniumManager(headless=False)
        else:
            self.selenium_manager = selenium_manager

        # Individual components (can still be used directly if needed)
        self.code_assistant = CodeAssistant(ollama_client)  # Granite-Code:8B
        self.planner = TaskPlanner(ollama_client)           # Hermes-3
        self.api_reverse_engineer = APIReverseEngineer(ollama_client)  # DeepSeek-R1 8B
        self.semantic_indexer = SemanticIndexer(ollama_client)  # mxbai-embed-large-v1

        # Main navigator component that uses the others
        self.web_navigator = WebNavigator(
            ollama_client, 
            self.selenium_manager, 
            db_session_factory=self._get_db_session_for_navigator
        )

    def _get_db_session_for_navigator(self):
        """Get a database session."""
        from core.database.database import SessionLocal
        return SessionLocal()

    async def perform_web_goal(self, user_goal: str):
        """
        Main entry point: orchestrates the multi-model system to achieve a user's web-related goal.
        
        This implements the flow in plan.md:
        1. Hermes-3 creates a plan
        2. Granite-Code generates the execution code
        3. As actions are taken, requests are captured
        4. DeepSeek-R1 analyzes the API interactions
        5. mxbai-embed stores and connects the semantic knowledge
        
        Args:
            user_goal: The user's goal expressed in natural language
        """
        console.print(f"Navigator (Orchestrator) received web goal: [bold green]{user_goal}[/bold green]")
        try:
            # Step 1: Initial planning using Hermes-3 via TaskPlanner
            # Gather context for the detailed plan
            current_url = self.web_navigator.current_url
            page_content = self.web_navigator.page_content
            api_history = self.web_navigator.captured_apis

            detailed_plan = await self.planner.create_detailed_plan(
                user_goal=user_goal,
                current_url=current_url,
                page_content=page_content,
                api_history=api_history
            )
            console.print(f"Detailed plan from Orchestrator:\n[yellow]{detailed_plan}[/yellow]")
            
            # Step 2: Execute the plan using WebNavigator
            await self.web_navigator.navigate_and_learn(user_goal, plan=detailed_plan)
            
            # Step 3: Summarize what was learned
            summary = await self.summarize_results(user_goal)
            console.print(f"Summary of learnings:\n[cyan]{summary}[/cyan]")
            
        finally:
            # Always ensure browser is closed
            self.web_navigator.close_browser()
        
        console.print(f"Navigator (Orchestrator) finished web goal: [bold green]{user_goal}[/bold green]")
    
    async def summarize_results(self, user_goal: str) -> str:
        """
        Get a summary of the navigation and what was learned.
        
        Args:
            user_goal: The original user goal
            
        Returns:
            A natural language summary of what was learned
        """
        # Get recent memories related to this goal
        memories = await self.semantic_indexer.search_memory(user_goal, top_k=10)
        
        # Extract captured APIs
        api_memories = [m for m in memories if m.get('metadata', {}).get('type') == 'api_request']
        
        # Format API info for the prompt
        api_info = ""
        if api_memories:
            api_info = "APIs discovered:\n"
            for i, api in enumerate(api_memories):
                api_info += f"{i+1}. {api.get('text', '')[:200]}...\n"
        
        # Get summary from Hermes
        prompt = (
            f"You are Hermes-3, an expert AI assistant skilled at summarizing information. "
            f"Summarize what was learned while pursuing this web automation goal: '{user_goal}'.\\n\\n"
            f"Context:\\n"
            f"{api_info}\\n"
            f"Focus your summary on these key aspects:\\n"
            f"1. What was the primary outcome or accomplishment related to the goal?\\n"
            f"2. What specific API patterns, request structures, or key UI elements were discovered or interacted with?\\n"
            f"3. What insights or learned patterns could be useful for future automation tasks related to this website or goal?\\n"
            f"Keep the summary concise and informative."
        )
        
        response = await self.ollama_client.generate_text(prompt, model_type="general")
        return response.get('response', 'No summary available.')
    
    async def api_search(self, query: str) -> list:
        """
        Search for API patterns matching a specific query.
        
        Args:
            query: The search query
            
        Returns:
            List of matching API memories
        """
        return await self.semantic_indexer.search_memory(query, top_k=5)
    
    async def generate_code_for_task(self, task_description: str) -> str:
        """
        Direct access to the code generator for a specific task.
        
        Args:
            task_description: Description of the task to code
            
        Returns:
            Generated code as text
        """
        return await self.code_assistant.generate_code(task_description)
