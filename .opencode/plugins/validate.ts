import type { Plugin } from "@opencode-ai/plugin"

const validatePlugin: Plugin = async (input) => {
  const { $ } = input

  return {
    "tool.execute.after": async (toolInput, toolOutput) => {
      const { tool, args } = toolInput

      if (tool !== "write" && tool !== "edit") {
        return
      }

      const filePath = args?.file_path || args?.filePath
      if (!filePath || typeof filePath !== "string") {
        return
      }

      if (!filePath.includes("knowledge/articles/") || !filePath.endsWith(".json")) {
        return
      }

      try {
        const result = await $`python3 hooks/validate_json.py ${filePath}`.nothrow()

        if (result.exitCode !== 0) {
          const validationOutput = result.stdout.toString() + result.stderr.toString()
          toolOutput.output = toolOutput.output + "\n\n[JSON 校验失败]\n" + validationOutput
        } else {
          toolOutput.output = toolOutput.output + "\n\n[JSON 校验通过]"
        }
      } catch (error) {
        console.error("JSON 校验插件异常:", error)
      }
    },
  }
}

export default validatePlugin
