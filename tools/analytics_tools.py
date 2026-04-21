import os
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg') # Headless mode for server environments
import pandas as pd
from datetime import datetime, timedelta
from langchain_core.tools import tool
from database.manager import get_expenses_in_range

# Output directory for charts
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORTS_DIR = os.path.join(BASE_DIR, "exports")
os.makedirs(EXPORTS_DIR, exist_ok=True)

def _get_date_range(timeframe: str):
    """Parses natural language timeframe into start and end dates."""
    now = datetime.now()
    end_date = now.strftime("%Y-%m-%d")
    
    t = timeframe.lower()
    if "today" in t:
        start_date = end_date
    elif "week" in t:
        start_date = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    elif "month" in t:
        # Start of current month
        start_date = now.replace(day=1).strftime("%Y-%m-%d")
    elif "year" in t:
        start_date = now.replace(month=1, day=1).strftime("%Y-%m-%d")
    else:
        # Default to last 30 days if unclear
        start_date = (now - timedelta(days=30)).strftime("%Y-%m-%d")
        
    return start_date, end_date

@tool
def generate_chart(user_id: int, chart_type: str, timeframe: str):
    """
    Generates a financial chart based on user request.
    - chart_type: Must be 'pie' (breakdown), 'line' (trends), or 'bar' (comparison).
    - timeframe: Natural language period like 'today', 'this week', 'this month', 'this year'.
    """
    start_date, end_date = _get_date_range(timeframe)
    data = get_expenses_in_range(user_id, start_date, end_date)
    
    if not data:
        return f"No transaction data found for {timeframe} ({start_date} to {end_date})."

    # Convert to DataFrame
    df = pd.DataFrame(data, columns=['amount', 'category', 'description', 'type', 'created_at'])
    df['amount'] = pd.to_numeric(df['amount'])
    
    plt.figure(figsize=(10, 6))
    filename = f"chart_{user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
    filepath = os.path.join(EXPORTS_DIR, filename)

    try:
        if chart_type.lower() == 'pie':
            # Spending breakdown by category
            expenses = df[df['type'] == 'expense']
            if expenses.empty:
                return "No expenses found to create a pie chart."
            category_totals = expenses.groupby('category')['amount'].sum()
            category_totals.plot(kind='pie', autopct='%1.1f%%', startangle=140, colormap='viridis')
            plt.title(f"Spending Breakdown ({timeframe})")
            plt.ylabel('')

        elif chart_type.lower() == 'line':
            # Spending trend over time
            expenses = df[df['type'] == 'expense']
            if expenses.empty:
                return "No expenses found to create a trend line."
            df['date'] = pd.to_datetime(df['created_at']).dt.date
            daily_totals = expenses.groupby('date')['amount'].sum()
            daily_totals.plot(kind='line', marker='o', color='tab:red', linewidth=2)
            plt.title(f"Spending Trend ({timeframe})")
            plt.xlabel("Date")
            plt.ylabel("Amount")
            plt.grid(True, linestyle='--', alpha=0.7)

        elif chart_type.lower() == 'bar':
            # Income vs Expense
            type_totals = df.groupby('type')['amount'].sum()
            type_totals.plot(kind='bar', color=['tab:red', 'tab:green'])
            plt.title(f"Income vs Expenses ({timeframe})")
            plt.ylabel("Amount")
            plt.xticks(rotation=0)
            
        else:
            return f"Unknown chart type requested: {chart_type}. Please ask for a pie, line, or bar chart."

        plt.tight_layout()
        plt.savefig(filepath)
        plt.close()
        
        return f'CHART_PATH:"{filepath}"'

    except Exception as e:
        plt.close()
        return f"Error generating chart: {str(e)}"
