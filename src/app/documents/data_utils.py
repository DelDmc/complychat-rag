import sys
from app.documents import process_documents


def main():
    # Check if the correct number of command-line arguments are provided
    if len(sys.argv) != 2:
        print("Usage: python run_functions.py function_name")
        return

    # Get the function name from the command-line argument
    function_name = sys.argv[1]

    # Check if the function exists in the module
    if not hasattr(process_documents, function_name):
        print(f"Function '{function_name}' not found in the module.")
        return

    # Call the function
    func = getattr(process_documents, function_name)
    func()

if __name__ == "__main__":
    main()