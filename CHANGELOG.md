### 6.1.1 [28-04-2025]
**Added** _inject_custom_css def
A function that finds css directives in the soup and applies to them locally.

Example: `[style=p-table--wide-table]` will apply 'p-table--wide-table' as a class the the element directly after where the directive was found.

### 6.1.1 [12-03-2025]
**Updated** EngagePages class
Pass values for the provided keys, even if the values are empty or null, as they can be a filter themselves.

### 6.1.0 [25-01-2025]
**Updated** Category class
Check for additions or deletions of topics within a category and update cached data if needed

### 6.0.0 [28-01-2025]
**Updated** Category class 
Removed to template handling from within the Category class.
Bump to 6.0.0, as the previous update was a major

### 5.8.0 [28-01-2025]
**Added** Category class 
A generic class for processing discourse categories and the topics they contain