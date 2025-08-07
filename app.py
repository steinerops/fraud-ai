import streamlit as st
import fitz  # PyMuPDF
import pikepdf
import tempfile
from datetime import datetime, timedelta
import traceback
import google.generativeai as genai
import json
import os

# Configure Gemini API
def configure_gemini():
    """Configure Gemini API with user's API key"""
    if 'gemini_api_key' not in st.session_state:
        st.session_state.gemini_api_key = ""
    
    if not st.session_state.gemini_api_key:
        api_key = st.text_input("Enter the Password:", type="password")
        if api_key:
            st.session_state.gemini_api_key = api_key
            genai.configure(api_key=api_key)
            return True
        else:
            st.warning("Please enter the Password to use AI analysis.")
            return False
    else:
        genai.configure(api_key=st.session_state.gemini_api_key)
        return True

def get_current_date_for_llm():
    """Get current date and format it for LLM context"""
    current_datetime = datetime.now()
    
    # Format as detailed date for LLM understanding
    formatted_date = current_datetime.strftime("%A, %B %d, %Y at %H:%M:%S IST")
    iso_date = current_datetime.strftime("%Y-%m-%d %H:%M:%S")
    
    return {
        "formatted": formatted_date,
        "iso": iso_date,
        "datetime_obj": current_datetime
    }

def analyze_metadata_with_llm(raw_metadata, creation_date_raw, mod_date_raw, quick_analysis_results):
    """Use Gemini 2.0 Flash to provide a professional analysis of PDF metadata"""
    try:
        model = genai.GenerativeModel('gemini-2.0-flash-exp')
        
        # Get current date with proper formatting
        current_date_info = get_current_date_for_llm()
        
        prompt = f"""
        You are a digital forensics expert providing a professional metadata analysis report.

        **TODAY'S DATE IS: {current_date_info['formatted']}**
        **FOR DATE COMPARISONS USE: {current_date_info['iso']}**

        **RAW PDF METADATA:**
        {json.dumps(raw_metadata, indent=2)}

        **RAW DATES:**
        Creation Date: {creation_date_raw}
        Modification Date: {mod_date_raw}

        **PROGRAM ANALYSIS RESULTS:**
        File Name: {quick_analysis_results['file_name']}
        Title: {quick_analysis_results['title'] or 'Not specified'}
        Author: {quick_analysis_results['author'] or 'Not specified'}
        Subject: {quick_analysis_results['subject'] or 'Not specified'}
        Keywords: {quick_analysis_results['keywords'] or 'Not specified'}
        Creator: {quick_analysis_results['creator'] or 'Not specified'}
        Producer: {quick_analysis_results['producer'] or 'Not specified'}
        Creation Date: {quick_analysis_results['creation_date'] or 'Not available'}
        Modification Date: {quick_analysis_results['modification_date'] or 'Not available'}
        Modification Status: {quick_analysis_results['modification_status']}
        Digital Signature: {quick_analysis_results['digital_signature']}

        **CRITICAL INSTRUCTIONS FOR DATE ANALYSIS:**
        - If BOTH Creation Date and Modification Date are missing/None: Document has no temporal metadata - focus on software legitimacy and other indicators
        - If Creation Date exists but Modification Date is missing: Document is likely original
        - If both dates exist and are DIFFERENT: Document was definitively modified
        - If both dates exist and are SAME: Document is original
        - Do NOT mention "temporal comparison cannot be performed" - instead focus on available evidence

        **CRITICAL INSTRUCTIONS FOR MISSING DATES:**
        - When dates are missing, emphasize what CAN be determined from available metadata
        - Focus on Creator/Producer legitimacy and business context
        - For Crystal Reports with missing dates: This is common in automated report generation where timestamp metadata may be stripped
        - Provide confident assessment based on software signatures and metadata patterns

        **Provide a professional analysis in the following format:**

        **Document Timeline:**
        [Focus on software used for creation. If dates missing, explain this is common for certain automated tools and doesn't indicate tampering]

        **Modification History:**
        [If no dates available, state this definitively but explain it doesn't indicate modification - focus on software evidence]

        **Software Analysis:**
        [Identify the creation tools, their legitimacy, and business context - this is your strongest indicator when dates are missing]

        **Authenticity Assessment:**
        [Provide confident verdict based on available metadata, software legitimacy, and business context - avoid uncertainty language]

        **Guidelines:**
        - When dates are missing, lead with software analysis as primary authenticity indicator
        - Crystal Reports, Apache FOP, and similar business tools often strip or omit timestamp metadata
        - Missing dates ≠ suspicious - explain this is normal for certain document generation workflows
        - Be confident in your assessment based on available evidence
        - Write in professional, report-style language
        - Keep each section to 1-2 sentences
        - Provide definitive conclusions based on software signatures and metadata patterns
        """

        response = model.generate_content(prompt)
        return response.text

    except Exception as e:
        return f"Error analyzing with AI: {str(e)}"

def parse_pdf_date(date_str):
    """Parse PDF date string and convert to readable format"""
    try:
        if not date_str:
            return None
        
        # Remove D: prefix if present
        if date_str.startswith("D:"):
            date_str = date_str[2:]
        
        # Handle different timezone formats
        timezone_offset = timedelta(0)
        
        if date_str.endswith('Z'):
            date_str = date_str[:-1]
            timezone_offset = timedelta(hours=5, minutes=30)  # Convert to IST
        elif '+' in date_str:
            parts = date_str.split('+')
            date_str = parts[0]
        elif '-' in date_str and len(date_str) > 14:
            parts = date_str.split('-')
            date_str = parts[0]
        
        # Parse the basic date (YYYYMMDDHHMMSS)
        if len(date_str) >= 14:
            base_datetime = datetime.strptime(date_str[:14], "%Y%m%d%H%M%S")
        else:
            base_datetime = datetime.strptime(date_str, "%Y%m%d%H%M%S")
        
        # Apply timezone conversion
        final_datetime = base_datetime + timezone_offset
        return final_datetime.strftime("%Y-%m-%d %H:%M:%S IST")
        
    except Exception as e:
        return date_str  # Return original on error

def clean_metadata_string(value):
    """Clean PDF metadata strings by removing extra characters"""
    if not value:
        return None
    
    clean_value = str(value).strip()
    
    if clean_value.startswith('(') and clean_value.endswith(')'):
        clean_value = clean_value[1:-1]
    
    if clean_value in ['', 'None', 'null', '()', '( )']:
        return None
        
    return clean_value

def check_pdf_authenticity(uploaded_file):
    """Check PDF authenticity and return metadata"""
    
    # Create temporary file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
        temp_pdf.write(uploaded_file.read())
        temp_pdf_name = temp_pdf.name

    try:
        # Extract metadata using pikepdf
        with pikepdf.Pdf.open(temp_pdf_name) as pdf:
            raw_metadata = pdf.docinfo
            metadata = {k: str(v) for k, v in raw_metadata.items()}
            
            # Extract basic dates
            creation_date = metadata.get("/CreationDate")
            mod_date = metadata.get("/ModDate")
            
            # Extract additional metadata
            title = clean_metadata_string(metadata.get("/Title"))
            author = clean_metadata_string(metadata.get("/Author"))
            subject = clean_metadata_string(metadata.get("/Subject"))
            creator = clean_metadata_string(metadata.get("/Creator"))
            producer = clean_metadata_string(metadata.get("/Producer"))
            keywords = clean_metadata_string(metadata.get("/Keywords"))

        # Parse and convert dates
        creation_readable = parse_pdf_date(creation_date)
        mod_readable = parse_pdf_date(mod_date)

        # FIXED: Proper modification status logic
        if not mod_date or mod_date == creation_date:
            mod_status = "Original"
        else:
            mod_status = "Modified"

        # Check for digital signatures using PyMuPDF
        with fitz.open(temp_pdf_name) as doc:
            trailer = doc.pdf_trailer()
            has_signature = "SigFlags" in trailer

        # Prepare result with all metadata
        result = {
            "creation_date": creation_readable,
            "creation_date_raw": creation_date,
            "modification_date": mod_readable,
            "modification_date_raw": mod_date,
            "modification_status": mod_status,
            "digital_signature": "Present" if has_signature else "Not Present",
            "title": title,
            "author": author,
            "subject": subject,
            "creator": creator,
            "producer": producer,
            "keywords": keywords,
            "file_name": uploaded_file.name,
            "raw_metadata": metadata
        }
        
        return result, None

    except Exception as e:
        traceback.print_exc()
        return None, str(e)
    finally:
        # Clean up temporary file
        if os.path.exists(temp_pdf_name):
            os.unlink(temp_pdf_name)

# Streamlit app
def main():
    st.title("🔍 Advanced PDF Authenticity Checker with AI Analysis")
    st.write("Upload a PDF file to check its authenticity and get detailed AI-powered metadata analysis")
    
    # Display current system date for transparency
    current_date_info = get_current_date_for_llm()
    st.info(f"**System Date:** {current_date_info['formatted']}")
    
    # Configure Gemini API
    if not configure_gemini():
        return
    
    st.success("✅ AI is ready to be used!")
    
    # File uploader
    uploaded_file = st.file_uploader("Choose a PDF file", type="pdf")
    
    if uploaded_file is not None:
        st.write(f"**File uploaded:** {uploaded_file.name}")
        
        # Process button
        if st.button("🚀 Analyze PDF with AI"):
            with st.spinner("Processing PDF and generating AI analysis..."):
                result, error = check_pdf_authenticity(uploaded_file)
                
                if error:
                    st.error(f"Error processing PDF: {error}")
                else:
                    st.success("PDF processed successfully!")
                    
                    # Display basic results first
                    st.subheader("📊 Quick Analysis Results")
                    
                    # Create two columns for better layout
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.write("**Basic Information:**")
                        st.write(f"**File Name:** {result['file_name']}")
                        st.write(f"**Title:** {result['title'] or 'Not specified'}")
                        st.write(f"**Author:** {result['author'] or 'Not specified'}")
                        st.write(f"**Subject:** {result['subject'] or 'Not specified'}")
                        st.write(f"**Keywords:** {result['keywords'] or 'Not specified'}")
                    
                    with col2:
                        st.write("**Technical Details:**")
                        st.write(f"**Creator:** {result['creator'] or 'Not specified'}")
                        st.write(f"**Producer:** {result['producer'] or 'Not specified'}")
                        st.write(f"**Creation Date:** {result['creation_date'] or 'Not available'}")
                        st.write(f"**Modification Date:** {result['modification_date'] or 'Not available'}")
                    
                    # Authenticity indicators
                    st.subheader("🔒 Authenticity Indicators")
                    
                    # Modification status
                    if result['modification_status'] == "Original":
                        st.success(f"**Modification Status:** {result['modification_status']}")
                    else:
                        st.warning(f"**Modification Status:** {result['modification_status']}")
                    
                    # Digital signature
                    if result['digital_signature'] == "Present":
                        st.success(f"**Digital Signature:** {result['digital_signature']}")
                    else:
                        st.info(f"**Digital Signature:** {result['digital_signature']}")
                    
                    # AI Analysis Section
                    st.subheader("🤖 Professional Metadata Analysis")
                    
                    with st.spinner("Generating professional analysis..."):
                        ai_analysis = analyze_metadata_with_llm(
                            result['raw_metadata'], 
                            result['creation_date_raw'], 
                            result['modification_date_raw'],
                            result  # Pass the complete result as quick_analysis_results
                        )
                    
                    if ai_analysis.startswith("Error"):
                        st.error(ai_analysis)
                    else:
                        st.markdown(ai_analysis)
                    
                    # Raw metadata expander
                    with st.expander("🔍 View Raw Metadata"):
                        st.json(result['raw_metadata'])
                    
                    # Download results
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        # Download basic results as JSON
                        json_result = json.dumps(result, indent=2)
                        st.download_button(
                            label="📥 Download Basic Results (JSON)",
                            data=json_result,
                            file_name=f"{uploaded_file.name}_analysis.json",
                            mime="application/json"
                        )
                    
                    with col2:
                        # Download AI analysis as text
                        current_date_for_report = get_current_date_for_llm()
                        full_report = f"""
PDF AUTHENTICITY ANALYSIS REPORT
================================
File: {result['file_name']}
Analysis Date: {current_date_for_report['formatted']}

BASIC METADATA:
{json.dumps(result, indent=2)}

PROFESSIONAL ANALYSIS:
{ai_analysis}
                        """
                        st.download_button(
                            label="📥 Download Full AI Report (TXT)",
                            data=full_report,
                            file_name=f"{uploaded_file.name}_ai_analysis.txt",
                            mime="text/plain"
                        )

if __name__ == "__main__":
    main()


# import streamlit as st
# import fitz  # PyMuPDF
# import pikepdf
# import tempfile
# from datetime import datetime, timedelta
# import traceback
# import google.generativeai as genai
# import json
# import os

# # Configure Gemini API
# def configure_gemini():
#     """Configure Gemini API with user's API key"""
#     if 'gemini_api_key' not in st.session_state:
#         st.session_state.gemini_api_key = ""
    
#     if not st.session_state.gemini_api_key:
#         api_key = st.text_input("Enter your Gemini API Key:", type="password")
#         if api_key:
#             st.session_state.gemini_api_key = api_key
#             genai.configure(api_key=api_key)
#             return True
#         else:
#             st.warning("Please enter your Gemini API key to use AI analysis.")
#             return False
#     else:
#         genai.configure(api_key=st.session_state.gemini_api_key)
#         return True

# def get_current_date_for_llm():
#     """Get current date and format it for LLM context"""
#     current_datetime = datetime.now()
    
#     # Format as detailed date for LLM understanding
#     formatted_date = current_datetime.strftime("%A, %B %d, %Y at %H:%M:%S IST")
#     iso_date = current_datetime.strftime("%Y-%m-%d %H:%M:%S")
    
#     return {
#         "formatted": formatted_date,
#         "iso": iso_date,
#         "datetime_obj": current_datetime
#     }

# def analyze_metadata_with_llm(raw_metadata, creation_date_raw, mod_date_raw, quick_analysis_results):
#     """Use Gemini 2.0 Flash to provide a professional analysis of PDF metadata"""
#     try:
#         model = genai.GenerativeModel('gemini-2.0-flash-exp')
        
#         # Get current date with proper formatting
#         current_date_info = get_current_date_for_llm()
        
#         prompt = f"""
#         You are a digital forensics expert providing a professional metadata analysis report.

#         **TODAY'S DATE IS: {current_date_info['formatted']}**
#         **FOR DATE COMPARISONS USE: {current_date_info['iso']}**

#         **RAW PDF METADATA:**
#         {json.dumps(raw_metadata, indent=2)}

#         **RAW DATES:**
#         Creation Date: {creation_date_raw}
#         Modification Date: {mod_date_raw}

#         **PROGRAM ANALYSIS RESULTS:**
#         File Name: {quick_analysis_results['file_name']}
#         Title: {quick_analysis_results['title'] or 'Not specified'}
#         Author: {quick_analysis_results['author'] or 'Not specified'}
#         Subject: {quick_analysis_results['subject'] or 'Not specified'}
#         Keywords: {quick_analysis_results['keywords'] or 'Not specified'}
#         Creator: {quick_analysis_results['creator'] or 'Not specified'}
#         Producer: {quick_analysis_results['producer'] or 'Not specified'}
#         Creation Date: {quick_analysis_results['creation_date'] or 'Not available'}
#         Modification Date: {quick_analysis_results['modification_date'] or 'Not available'}
#         Modification Status: {quick_analysis_results['modification_status']}
#         Digital Signature: {quick_analysis_results['digital_signature']}

#         **CRITICAL INSTRUCTIONS FOR DATE ANALYSIS:**
#         - If BOTH Creation Date and Modification Date are missing/None: Document has no temporal metadata - focus on software legitimacy and other indicators
#         - If Creation Date exists but Modification Date is missing: Document is likely original
#         - If both dates exist and are DIFFERENT: Document was definitively modified
#         - If both dates exist and are SAME: Document is original
#         - Do NOT mention "temporal comparison cannot be performed" - instead focus on available evidence

#         **CRITICAL INSTRUCTIONS FOR MISSING DATES:**
#         - When dates are missing, emphasize what CAN be determined from available metadata
#         - Focus on Creator/Producer legitimacy and business context
#         - For Crystal Reports with missing dates: This is common in automated report generation where timestamp metadata may be stripped
#         - Provide confident assessment based on software signatures and metadata patterns

#         **Provide a professional analysis in the following format:**

#         **Document Timeline:**
#         [Focus on software used for creation. If dates missing, explain this is common for certain automated tools and doesn't indicate tampering]

#         **Modification History:**
#         [If no dates available, state this definitively but explain it doesn't indicate modification - focus on software evidence]

#         **Software Analysis:**
#         [Identify the creation tools, their legitimacy, and business context - this is your strongest indicator when dates are missing]

#         **Authenticity Assessment:**
#         [Provide confident verdict based on available metadata, software legitimacy, and business context - avoid uncertainty language]

#         **Guidelines:**
#         - When dates are missing, lead with software analysis as primary authenticity indicator
#         - Crystal Reports, Apache FOP, and similar business tools often strip or omit timestamp metadata
#         - Missing dates ≠ suspicious - explain this is normal for certain document generation workflows
#         - Be confident in your assessment based on available evidence
#         - Write in professional, report-style language
#         - Keep each section to 1-2 sentences
#         - Provide definitive conclusions based on software signatures and metadata patterns
#         """

#         response = model.generate_content(prompt)
#         return response.text

#     except Exception as e:
#         return f"Error analyzing with AI: {str(e)}"

# def parse_pdf_date(date_str):
#     """Parse PDF date string and convert to readable format"""
#     try:
#         if not date_str:
#             return None
        
#         # Remove D: prefix if present
#         if date_str.startswith("D:"):
#             date_str = date_str[2:]
        
#         # Handle different timezone formats
#         timezone_offset = timedelta(0)
        
#         if date_str.endswith('Z'):
#             date_str = date_str[:-1]
#             timezone_offset = timedelta(hours=5, minutes=30)  # Convert to IST
#         elif '+' in date_str:
#             parts = date_str.split('+')
#             date_str = parts[0]
#         elif '-' in date_str and len(date_str) > 14:
#             parts = date_str.split('-')
#             date_str = parts[0]
        
#         # Parse the basic date (YYYYMMDDHHMMSS)
#         if len(date_str) >= 14:
#             base_datetime = datetime.strptime(date_str[:14], "%Y%m%d%H%M%S")
#         else:
#             base_datetime = datetime.strptime(date_str, "%Y%m%d%H%M%S")
        
#         # Apply timezone conversion
#         final_datetime = base_datetime + timezone_offset
#         return final_datetime.strftime("%Y-%m-%d %H:%M:%S IST")
        
#     except Exception as e:
#         return date_str  # Return original on error

# def clean_metadata_string(value):
#     """Clean PDF metadata strings by removing extra characters"""
#     if not value:
#         return None
    
#     clean_value = str(value).strip()
    
#     if clean_value.startswith('(') and clean_value.endswith(')'):
#         clean_value = clean_value[1:-1]
    
#     if clean_value in ['', 'None', 'null', '()', '( )']:
#         return None
        
#     return clean_value

# def check_pdf_authenticity(uploaded_file):
#     """Check PDF authenticity and return metadata"""
    
#     # Create temporary file
#     with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
#         temp_pdf.write(uploaded_file.read())
#         temp_pdf_name = temp_pdf.name

#     try:
#         # Extract metadata using pikepdf
#         with pikepdf.Pdf.open(temp_pdf_name) as pdf:
#             raw_metadata = pdf.docinfo
#             metadata = {k: str(v) for k, v in raw_metadata.items()}
            
#             # Extract basic dates
#             creation_date = metadata.get("/CreationDate")
#             mod_date = metadata.get("/ModDate")
            
#             # Extract additional metadata
#             title = clean_metadata_string(metadata.get("/Title"))
#             author = clean_metadata_string(metadata.get("/Author"))
#             subject = clean_metadata_string(metadata.get("/Subject"))
#             creator = clean_metadata_string(metadata.get("/Creator"))
#             producer = clean_metadata_string(metadata.get("/Producer"))
#             keywords = clean_metadata_string(metadata.get("/Keywords"))

#         # Parse and convert dates
#         creation_readable = parse_pdf_date(creation_date)
#         mod_readable = parse_pdf_date(mod_date)

#         # FIXED: Proper modification status logic
#         if not mod_date or mod_date == creation_date:
#             mod_status = "Original"
#         else:
#             mod_status = "Modified"

#         # Check for digital signatures using PyMuPDF
#         with fitz.open(temp_pdf_name) as doc:
#             trailer = doc.pdf_trailer()
#             has_signature = "SigFlags" in trailer

#         # Prepare result with all metadata
#         result = {
#             "creation_date": creation_readable,
#             "creation_date_raw": creation_date,
#             "modification_date": mod_readable,
#             "modification_date_raw": mod_date,
#             "modification_status": mod_status,
#             "digital_signature": "Present" if has_signature else "Not Present",
#             "title": title,
#             "author": author,
#             "subject": subject,
#             "creator": creator,
#             "producer": producer,
#             "keywords": keywords,
#             "file_name": uploaded_file.name,
#             "raw_metadata": metadata
#         }
        
#         return result, None

#     except Exception as e:
#         traceback.print_exc()
#         return None, str(e)
#     finally:
#         # Clean up temporary file
#         if os.path.exists(temp_pdf_name):
#             os.unlink(temp_pdf_name)

# # Streamlit app
# def main():
#     st.title("🔍 Advanced PDF Authenticity Checker with AI Analysis")
#     st.write("Upload a PDF file to check its authenticity and get detailed AI-powered metadata analysis")
    
#     # Display current system date for transparency
#     current_date_info = get_current_date_for_llm()
#     st.info(f"**System Date:** {current_date_info['formatted']}")
    
#     # Configure Gemini API
#     if not configure_gemini():
#         return
    
#     st.success("✅ Gemini AI is configured and ready!")
    
#     # File uploader
#     uploaded_file = st.file_uploader("Choose a PDF file", type="pdf")
    
#     if uploaded_file is not None:
#         st.write(f"**File uploaded:** {uploaded_file.name}")
        
#         # Process button
#         if st.button("🚀 Analyze PDF with AI"):
#             with st.spinner("Processing PDF and generating AI analysis..."):
#                 result, error = check_pdf_authenticity(uploaded_file)
                
#                 if error:
#                     st.error(f"Error processing PDF: {error}")
#                 else:
#                     st.success("PDF processed successfully!")
                    
#                     # Display basic results first
#                     st.subheader("📊 Quick Analysis Results")
                    
#                     # Create two columns for better layout
#                     col1, col2 = st.columns(2)
                    
#                     with col1:
#                         st.write("**Basic Information:**")
#                         st.write(f"**File Name:** {result['file_name']}")
#                         st.write(f"**Title:** {result['title'] or 'Not specified'}")
#                         st.write(f"**Author:** {result['author'] or 'Not specified'}")
#                         st.write(f"**Subject:** {result['subject'] or 'Not specified'}")
#                         st.write(f"**Keywords:** {result['keywords'] or 'Not specified'}")
                    
#                     with col2:
#                         st.write("**Technical Details:**")
#                         st.write(f"**Creator:** {result['creator'] or 'Not specified'}")
#                         st.write(f"**Producer:** {result['producer'] or 'Not specified'}")
#                         st.write(f"**Creation Date:** {result['creation_date'] or 'Not available'}")
#                         st.write(f"**Modification Date:** {result['modification_date'] or 'Not available'}")
                    
#                     # Authenticity indicators
#                     st.subheader("🔒 Authenticity Indicators")
                    
#                     # Modification status
#                     if result['modification_status'] == "Original":
#                         st.success(f"**Modification Status:** {result['modification_status']}")
#                     else:
#                         st.warning(f"**Modification Status:** {result['modification_status']}")
                    
#                     # Digital signature
#                     if result['digital_signature'] == "Present":
#                         st.success(f"**Digital Signature:** {result['digital_signature']}")
#                     else:
#                         st.info(f"**Digital Signature:** {result['digital_signature']}")
                    
#                     # AI Analysis Section
#                     st.subheader("🤖 Professional Metadata Analysis")
                    
#                     with st.spinner("Generating professional analysis..."):
#                         ai_analysis = analyze_metadata_with_llm(
#                             result['raw_metadata'], 
#                             result['creation_date_raw'], 
#                             result['modification_date_raw'],
#                             result  # Pass the complete result as quick_analysis_results
#                         )
                    
#                     if ai_analysis.startswith("Error"):
#                         st.error(ai_analysis)
#                     else:
#                         st.markdown(ai_analysis)
                    
#                     # Raw metadata expander
#                     with st.expander("🔍 View Raw Metadata"):
#                         st.json(result['raw_metadata'])
                    
#                     # Download results
#                     col1, col2 = st.columns(2)
                    
#                     with col1:
#                         # Download basic results as JSON
#                         json_result = json.dumps(result, indent=2)
#                         st.download_button(
#                             label="📥 Download Basic Results (JSON)",
#                             data=json_result,
#                             file_name=f"{uploaded_file.name}_analysis.json",
#                             mime="application/json"
#                         )
                    
#                     with col2:
#                         # Download AI analysis as text
#                         current_date_for_report = get_current_date_for_llm()
#                         full_report = f"""
# PDF AUTHENTICITY ANALYSIS REPORT
# ================================
# File: {result['file_name']}
# Analysis Date: {current_date_for_report['formatted']}

# BASIC METADATA:
# {json.dumps(result, indent=2)}

# PROFESSIONAL ANALYSIS:
# {ai_analysis}
#                         """
#                         st.download_button(
#                             label="📥 Download Full AI Report (TXT)",
#                             data=full_report,
#                             file_name=f"{uploaded_file.name}_ai_analysis.txt",
#                             mime="text/plain"
#                         )

# if __name__ == "__main__":
#     main()
